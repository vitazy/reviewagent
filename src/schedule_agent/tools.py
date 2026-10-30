from __future__ import annotations

import sqlite3
from collections import Counter
from datetime import timedelta

from pydantic import ValidationError

from .context import RuntimeContext
from .guards import canonical_items, canonical_request, idempotency_key, validate_candidates, validate_result
from .schemas import (AssetArgs, ConfirmArgs, Confirmation, FinishArgs, SaveArgs, SlotArgs,
                      ToolObservation, utc)
from .storage import BusinessError, get_asset, occupied, persist
from .rules import load_rules

ARGUMENTS = {"read_asset": AssetArgs, "check_rules": AssetArgs, "query_slots": SlotArgs,
             "request_confirmation": ConfirmArgs, "save_draft": SaveArgs, "finish": FinishArgs}
DESCRIPTIONS = {
    "read_asset": "读取本地素材元数据；缺字段时至少再读一次补查。",
    "check_rules": "检查本地素材规则，返回风险、缺字段及证据。risk_reasons必须完整引用。",
    "query_slots": "查询指定时段及同日后续可用整点，不提供发布能力。",
    "request_confirmation": "提出待确认问题；具体时间/风险确认必须绑定类型与范围，回答来自外部预设。",
    "save_draft": "仅保存合法候选草稿。idempotency_key传auto由代码算哈希。失败可重试一次。",
    "finish": "提交最终结果，参数必须通过证据与业务护栏；失败后按observation修正。",
}


def tool_schemas():
    return [{"type": "function", "function": {"name": name, "description": DESCRIPTIONS[name],
             "parameters": model.model_json_schema()}} for name, model in ARGUMENTS.items()]


def failure(kind: str, message: str) -> dict:
    return ToolObservation(ok=False, error={"type": kind, "message": message}).model_dump(mode="json")


class FaultInjector:
    def __init__(self, specification=""):
        self.targets: dict[str, set[int]] = {}
        self.counts = Counter()
        for entry in specification.split(",") if specification else []:
            name, sep, count = entry.strip().partition(":")
            if not sep or name not in ARGUMENTS or name == "finish" or not count.isdigit() or int(count) < 1:
                raise ValueError("faults必须为已知业务工具名:正整数，不能注入finish")
            self.targets.setdefault(name, set()).add(int(count))

    def hit(self, name):
        self.counts[name] += 1
        if self.counts[name] in self.targets.get(name, set()):
            raise BusinessError("InjectedFailure", f"{name}第{self.counts[name]}次调用故障注入")


class ToolExecutor:
    def __init__(self, ctx: RuntimeContext, faults=""):
        self.ctx = ctx
        self.faults = FaultInjector(faults)
        self.last_args = {}

    def execute(self, name: str, args: dict) -> dict:
        self.last_args = args
        try:
            if name not in ARGUMENTS:
                raise BusinessError("UnknownTool", "工具不在注册表中")
            parsed = ARGUMENTS[name].model_validate(args)
            self.last_args = parsed.model_dump(mode="json")
            if isinstance(parsed, AssetArgs) and parsed.asset_id not in self.ctx.request.asset_ids:
                raise BusinessError("GuardViolation", "工具不能访问请求外素材")
            if name == "save_draft":
                validate_candidates(self.ctx, parsed.items)
                key = idempotency_key(self.ctx, parsed.items)
                if parsed.idempotency_key not in ("auto", key):
                    raise BusinessError("GuardViolation", "idempotency_key与代码计算结果不一致，请使用auto")
                self.last_args["idempotency_key"] = key
                if self.ctx.save_attempts >= 2:
                    raise BusinessError("RetryLimitExceeded", "每次运行最多两次持久化尝试")
                self.ctx.save_attempts += 1
                self.faults.hit(name)
                data = persist(self.ctx.db_path, key, canonical_request(self.ctx), canonical_items(self.ctx, parsed.items))
                data["result_items"] = [item.model_dump(mode="json") for item in parsed.items]
            elif name == "finish":
                validate_result(self.ctx, parsed.result)
                data = parsed.result.model_dump(mode="json")
            else:
                self.faults.hit(name)
                data = getattr(self, "_" + name)(parsed)
            observation = ToolObservation(ok=True, data=data).model_dump(mode="json")
        except ValidationError:
            observation = failure("InvalidArguments", "参数不符合工具JSON schema，请核对必填字段、类型、时间和多余字段")
        except BusinessError as exc:
            observation = failure(exc.kind, str(exc))
        except sqlite3.Error:
            observation = failure("StorageError", "本地数据库操作未获成功确认，请核实数据或重试")
        except Exception:
            observation = failure("ToolError", "本地工具执行失败；未取得可用证据")
        self.ctx.observe(name, self.last_args, observation)
        return observation

    def _rules(self):
        return load_rules(self.ctx)

    def _read_asset(self, args):
        asset = get_asset(self.ctx.db_path, args.asset_id)
        asset["missing_fields"] = [f for f in self._rules()["required_fields"] if not asset.get(f)]
        asset["rules_fingerprint"] = self.ctx.rules_fingerprint
        return asset

    def _check_rules(self, args):
        asset = get_asset(self.ctx.db_path, args.asset_id)
        rules = self._rules()
        missing = [f for f in rules["required_fields"] if not asset.get(f)]
        codes = []
        if any(word in asset["content"] for word in rules["prohibited_words"]):
            codes.append("prohibited_word")
        if not asset["music_authorized"]:
            codes.append("unauthorized_music")
        if asset["copyright_status"] and asset["copyright_status"] != rules["copyright_required"]:
            codes.append("copyright_unlicensed")
        high = bool(codes)
        if asset["manual_review_required"]:
            codes.append("manual_review")
        reasons = [rules["risk_reasons"][c] for c in codes]
        if missing:
            reasons.append("缺少必填字段：" + ",".join(missing))
        return {"asset_id": args.asset_id, "risk_level": "high" if high else ("low" if codes else "none"),
                "risk_codes": codes, "risk_reasons": reasons, "missing_fields": missing,
                "rule_version": rules["version"], "revision": asset["revision"],
                "rules_fingerprint": self.ctx.rules_fingerprint}

    def _query_slots(self, args):
        if args.channel != self.ctx.request.channel or args.date != args.around_time.date().isoformat():
            raise BusinessError("InvalidArguments", "渠道必须匹配请求，date必须匹配around_time业务日期")
        busy = occupied(self.ctx.db_path, args.channel)
        nearby = []
        candidate = args.around_time + timedelta(hours=1)
        while candidate.date() == args.around_time.date():
            if utc(candidate) not in busy:
                nearby.append(candidate.isoformat())
            candidate += timedelta(hours=1)
        return {"channel": args.channel, "date": args.date, "requested_time": args.around_time.isoformat(),
                "requested_available": utc(args.around_time) not in busy, "nearby_available": nearby,
                "occupied_times": sorted(busy)}

    def _request_confirmation(self, args):
        confirmation = None
        status = "pending"
        if args.confirmation_type:
            probe = Confirmation(asset_id=args.asset_id, kind=args.confirmation_type, accepted=True,
                                 proposed_time=args.proposed_time, risk_codes=args.risk_codes)
            for answer in self.ctx.preset_answers:
                if (answer.asset_id, answer.kind, answer.proposed_time, answer.risk_codes) == (
                        probe.asset_id, probe.kind, probe.proposed_time, probe.risk_codes):
                    confirmation = answer.model_dump(mode="json")
                    status = "accepted" if answer.accepted else "rejected"
        return {"asset_id": args.asset_id, "question": args.question, "status": status,
                "confirmation_type": args.confirmation_type, "proposed_time": args.proposed_time.isoformat() if args.proposed_time else None,
                "risk_codes": args.risk_codes, "confirmation": confirmation}
