from __future__ import annotations

import hashlib
import json
import unicodedata
from datetime import datetime

from .context import RuntimeContext
from .schemas import AgentResult, AssetResult, Confirmation, PendingItem, utc
from .storage import BusinessError, verify_saved
from .rules import load_rules


def require(condition: bool, message: str):
    if not condition:
        raise BusinessError("GuardViolation", message)


def check_words(value):
    if isinstance(value, str):
        normalized = "".join(unicodedata.normalize("NFKC", value).split())
        require(not any(word in normalized for word in ("已发布", "已上线")), "结果只能描述草稿，含禁止的发布表述")
    elif isinstance(value, dict):
        for v in value.values():
            check_words(v)
    elif isinstance(value, list):
        for v in value:
            check_words(v)


def confirmed(ctx: RuntimeContext, asset_id: str, kind: str, time=None, codes=()) -> bool:
    matches = [c for c in ctx.confirmations if c.asset_id == asset_id and c.kind == kind
               and (kind != "time_change" or (time is not None and utc(c.proposed_time) == utc(time)))
               and (kind != "risk_ack" or set(c.risk_codes) == set(codes))]
    return bool(matches and matches[-1].accepted)


def slot_available(ctx: RuntimeContext, time) -> bool:
    iso = datetime.fromisoformat(time) if isinstance(time, str) else time
    for observation in reversed(ctx.slots):
        if observation["channel"] != ctx.request.channel or observation["date"] != iso.date().isoformat():
            continue
        candidates = list(observation["nearby_available"])
        if observation["requested_available"]:
            candidates.append(observation["requested_time"])
        return utc(iso) in {utc(t) for t in candidates}
    return False


def review_state(check: dict) -> str:
    if check["risk_level"] == "high":
        return "blocked"
    return "needs_info" if check["missing_fields"] else "approved"


def validate_item(ctx: RuntimeContext, item: AssetResult, saving=False):
    require(item.asset_id in ctx.request.asset_ids, "结果包含请求外素材")
    req = ctx.request.requested_times[item.asset_id]
    require(item.requested_time == req.time, "不得改写原 requested_time")
    reads = ctx.reads.get(item.asset_id, [])
    check = ctx.checks.get(item.asset_id)
    require(bool(reads) and check is not None, "缺少成功读取或规则审核证据")
    load_rules(ctx)
    if check.get("rules_fingerprint") != ctx.rules_fingerprint:
        raise BusinessError("StaleReview", "审核规则已变化，必须重新check_rules后再保存或结束")
    require(reads[-1]["revision"] == check["revision"], "素材修订与审核证据不一致，需重新审核")
    require(item.review_status == review_state(check), "审核状态与规则证据不一致")
    require(set(item.risk_reasons) == set(check["risk_reasons"]), "风险原因必须完整引用工具返回，不得删改")
    if item.review_status == "needs_info":
        require(len(reads) >= 2, "信息缺失后必须至少补查一次")
    if item.review_status != "approved":
        require(item.suggested_time is None, "高风险或资料不全不能排期")
        require(not saving, "高风险或资料不全不能保存")
    if check["risk_level"] == "low":
        require(item.needs_confirmation and bool(item.confirmation_reason), "低风险必须保留确认标记与原因")
    if item.suggested_time is not None:
        require(slot_available(ctx, item.suggested_time), "缺少该候选时段的可用查询证据")
        require(item.suggested_time.date() == req.time.date() and item.suggested_time >= req.time,
                "只允许同日原时段或后续候选")
        if item.suggested_time != req.time:
            require(item.needs_confirmation and bool(item.confirmation_reason), "改时必须标记确认并说明原因")
            if req.type == "hard":
                require(confirmed(ctx, item.asset_id, "time_change", item.suggested_time), "hard改时缺少匹配的可信确认")
    elif saving:
        require(False, "无建议时段不能保存")
    check_words(item.model_dump(mode="json"))


def validate_candidates(ctx: RuntimeContext, items: list[AssetResult]):
    require(bool(items), "不能保存空草稿")
    require(len({i.asset_id for i in items}) == len(items), "保存素材重复")
    slots = set()
    for item in items:
        validate_item(ctx, item, saving=True)
        signature = utc(item.suggested_time)
        require(signature not in slots, "本草稿内部时段冲突")
        slots.add(signature)


def canonical_confirmation(c: Confirmation) -> dict:
    return {"asset_id": c.asset_id, "kind": c.kind, "accepted": c.accepted,
            "proposed_time": utc(c.proposed_time) if c.proposed_time else None,
            "risk_codes": sorted(c.risk_codes)}


def canonical_request(ctx: RuntimeContext) -> dict:
    req = ctx.request
    return {"asset_ids": sorted(req.asset_ids), "channel": req.channel,
            "requested_times": {a: {"time": utc(req.requested_times[a].time), "type": req.requested_times[a].type}
                                for a in sorted(req.asset_ids)},
            "confirmations": sorted([canonical_confirmation(c) for c in req.confirmations], key=stable_json)}


def stable_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_items(ctx: RuntimeContext, items: list[AssetResult]) -> list[dict]:
    result = []
    for item in sorted(items, key=lambda i: i.asset_id):
        codes = sorted(ctx.checks[item.asset_id]["risk_codes"])
        # Only confirmations relevant to this candidate enter the persisted facts.
        acknowledgements = []
        if item.suggested_time != item.requested_time:
            acknowledgements.append({"kind": "time_change", "accepted": confirmed(
                ctx, item.asset_id, "time_change", item.suggested_time)})
        if ctx.checks[item.asset_id]["risk_level"] == "low":
            acknowledgements.append({"kind": "risk_ack", "accepted": confirmed(
                ctx, item.asset_id, "risk_ack", codes=codes)})
        result.append({"asset_id": item.asset_id, "channel": ctx.request.channel,
                       "review_status": item.review_status, "requested_time": utc(item.requested_time),
                       "suggested_time": utc(item.suggested_time) if item.suggested_time else None,
                       "risk_codes": codes, "needs_confirmation": item.needs_confirmation,
                       "confirmations": acknowledgements})
    return result


def idempotency_key(ctx: RuntimeContext, items: list[AssetResult]) -> str:
    payload = {"request": canonical_request(ctx), "items": canonical_items(ctx, items)}
    return hashlib.sha256(stable_json(payload).encode("utf-8")).hexdigest()


def projected_item(ctx: RuntimeContext, asset_id: str, reserved=None) -> AssetResult | None:
    """Evidence projection for partial exits and the offline mock; selects no tools."""
    check = ctx.checks.get(asset_id)
    if not check or not ctx.reads.get(asset_id):
        return None
    if ctx.rules_fingerprint and check.get("rules_fingerprint") != ctx.rules_fingerprint:
        return None
    if ctx.reads[asset_id][-1]["revision"] != check["revision"]:
        return None
    status = review_state(check)
    if status == "needs_info" and len(ctx.reads[asset_id]) < 2:
        return None
    requested = ctx.request.requested_times[asset_id]
    suggested = None
    reserved = reserved or set()
    if status == "approved":
        if slot_available(ctx, requested.time) and requested.time not in reserved:
            suggested = requested.time
        else:
            for observation in reversed(ctx.slots):
                if observation["channel"] == ctx.request.channel and observation["date"] == requested.time.date().isoformat():
                    for time in observation["nearby_available"]:
                        if datetime.fromisoformat(time) not in reserved and datetime.fromisoformat(time) >= requested.time and (requested.type == "soft" or confirmed(
                                ctx, asset_id, "time_change", time)):
                            suggested = datetime.fromisoformat(time)
                            break
                    break
    changed = suggested is not None and suggested != requested.time
    low = check["risk_level"] == "low"
    reason = []
    if changed:
        reason.append("时间有调整；" + ("已确认" if confirmed(ctx, asset_id, "time_change", suggested) else "待确认"))
    if low:
        reason.append("边界风险；" + ("已确认" if confirmed(ctx, asset_id, "risk_ack", codes=check["risk_codes"]) else "待人工复核"))
    return AssetResult(asset_id=asset_id, review_status=status, risk_reasons=check["risk_reasons"],
                       requested_time=requested.time, suggested_time=suggested, needs_confirmation=changed or low,
                       confirmation_reason="；".join(reason) or None)


def required_pending(ctx: RuntimeContext, items: list[AssetResult]) -> list[PendingItem]:
    pending = []
    for item in items:
        aid = item.asset_id
        if item.review_status != "approved":
            pending.append(PendingItem(asset_id=aid, kind=item.review_status, message="；".join(item.risk_reasons)))
        else:
            if item.suggested_time is None:
                kind = "time_confirmation" if ctx.request.requested_times[aid].type == "hard" else "slot_unavailable"
                pending.append(PendingItem(asset_id=aid, kind=kind, message="原时段不可用；需确认可用候选或调整要求"))
            elif item.suggested_time != item.requested_time and not confirmed(ctx, aid, "time_change", item.suggested_time):
                pending.append(PendingItem(asset_id=aid, kind="time_confirmation", message="建议时间变更待确认",
                                           proposed_time=item.suggested_time))
            check = ctx.checks[aid]
            if check["risk_level"] == "low" and not confirmed(ctx, aid, "risk_ack", codes=check["risk_codes"]):
                pending.append(PendingItem(asset_id=aid, kind="risk_confirmation", message="边界风险需人工复核",
                                           risk_codes=check["risk_codes"]))
    if ctx.save_attempts and not ctx.saves:
        pending.append(PendingItem(kind="save_failure", message="草稿保存未获成功确认；如为存储异常需核实数据库状态"))
    return pending


def draft_truth(ctx: RuntimeContext) -> tuple[str, str | None]:
    if ctx.saves:
        return ctx.saves[-1]["draft_status"], ctx.saves[-1]["draft_id"]
    return ("failed" if ctx.save_attempts else "not_saved"), None


def build_result(ctx: RuntimeContext, forced_status: str | None = None, message: str = "") -> AgentResult:
    if forced_status:
        try:
            load_rules(ctx)
        except BusinessError:
            pass  # Unavailable rules invalidate unpersisted review evidence, not the partial exit.
    items = []
    reserved = set()
    saved_times = {i["asset_id"]: i["suggested_time"] for i in ctx.saves[-1]["items"]} if ctx.saves else {}
    saved_results = {i["asset_id"]: i for i in ctx.saves[-1]["result_items"]} if ctx.saves else {}
    for aid in ctx.request.asset_ids:
        item = (AssetResult.model_validate(saved_results[aid]) if forced_status and aid in saved_results
                else projected_item(ctx, aid, reserved))
        if item is not None:
            if forced_status and ctx.saves and aid not in saved_times:
                item.suggested_time = None
            if item.suggested_time is not None:
                reserved.add(item.suggested_time)
            items.append(item)
    pending = required_pending(ctx, items)
    if forced_status and ctx.rules_fingerprint:
        pending.extend(PendingItem(asset_id=aid, kind="rules_changed", message="审核规则已变化，已有审核或保存快照需重新核对")
                       for aid, check in ctx.checks.items() if check.get("rules_fingerprint") != ctx.rules_fingerprint)
    done = {i.asset_id for i in items}
    pending.extend(PendingItem(asset_id=a, kind="unprocessed", message="尚未取得完整审核证据")
                   for a in ctx.request.asset_ids if a not in done)
    if forced_status:
        pending.append(PendingItem(kind="budget_exhausted" if forced_status == "incomplete_step_limit" else "model_error",
                                   message=message))
    draft_status, draft_id = draft_truth(ctx)
    return AgentResult(items=items, draft_status=draft_status, draft_id=draft_id,
                       status=forced_status or ("needs_attention" if pending else "completed"), pending_items=pending)


def pending_signature(p: PendingItem):
    return p.asset_id, p.kind, utc(p.proposed_time) if p.proposed_time else None, tuple(sorted(p.risk_codes))


def pending_covers(ctx, expected, actual):
    if expected.kind != actual.kind:
        return False
    if expected.asset_id != actual.asset_id:
        if not (expected.kind == "save_failure" and expected.asset_id is None and actual.asset_id in ctx.request.asset_ids):
            return False
    if expected.proposed_time is not None:
        if actual.proposed_time != expected.proposed_time:
            return False
    elif actual.proposed_time is not None:
        if expected.kind != "time_confirmation" or actual.asset_id not in ctx.request.asset_ids:
            return False
        req = ctx.request.requested_times[actual.asset_id]
        if req.type != "hard" or actual.proposed_time < req.time or actual.proposed_time.date() != req.time.date() or not slot_available(ctx, actual.proposed_time):
            return False
    if expected.risk_codes:
        return set(actual.risk_codes) == set(expected.risk_codes)
    if actual.risk_codes:
        return set(actual.risk_codes) == set(ctx.checks.get(actual.asset_id, {}).get("risk_codes", []))
    return True


def validate_result(ctx: RuntimeContext, result: AgentResult, partial=False):
    check_words(result.model_dump(mode="json"))
    ids = [i.asset_id for i in result.items]
    require(len(ids) == len(set(ids)), "结果素材重复")
    require(set(ids) <= set(ctx.request.asset_ids), "结果包含未知素材")
    if not partial:
        require(set(ids) == set(ctx.request.asset_ids), "finish必须覆盖所有输入素材")
        require(result.status in ("completed", "needs_attention"), "模型不能伪造运行时终止状态")
    saved_results = {i["asset_id"]: i for i in ctx.saves[-1]["result_items"]} if partial and ctx.saves else {}
    for item in result.items:
        if item.asset_id in saved_results:
            require(item.model_dump(mode="json") == saved_results[item.asset_id], "部分结果必须保留已保存快照")
        else:
            validate_item(ctx, item)
    candidates = [i for i in result.items if i.suggested_time is not None]
    if candidates and not saved_results:
        validate_candidates(ctx, candidates)
    if not partial:
        reserved = {i.suggested_time for i in candidates}
        for item in result.items:
            if item.review_status != "approved" or item.suggested_time is not None:
                continue
            req = ctx.request.requested_times[item.asset_id]
            observations = [s for s in ctx.slots if s["channel"] == ctx.request.channel
                            and s["date"] == req.time.date().isoformat()]
            require(bool(observations), "未查询时段，不能断言没有可保存候选")
            latest = observations[-1]
            available = [datetime.fromisoformat(t) for t in latest["nearby_available"]]
            if latest["requested_available"]:
                available.append(datetime.fromisoformat(latest["requested_time"]))
            eligible = [t for t in available if t >= req.time and t not in reserved
                        and (t == req.time or req.type == "soft" or confirmed(ctx, item.asset_id, "time_change", t))]
            require(not eligible, "存在合法空闲候选，不能省略建议来跳过保存")
    require((result.draft_status, result.draft_id) == draft_truth(ctx), "保存状态或ID不符合真实工具返回")
    if ctx.saves:
        saved = ctx.saves[-1]
        if partial:
            require({i.asset_id for i in candidates} == set(saved_results), "部分结果不能把未保存候选当成已保存")
        else:
            require(canonical_items(ctx, candidates) == saved["items"], "最终排期与已保存草稿不一致")
            require(verify_saved(ctx.db_path, saved), "数据库没有对应的真实草稿内容")
    elif candidates and not partial:
        require(ctx.save_attempts > 0, "有合法候选时必须先尝试保存")
    required = required_pending(ctx, result.items)
    actual_signatures = {pending_signature(p) for p in result.pending_items}
    missing = [p for p in required if not any(pending_covers(ctx, p, actual) for actual in result.pending_items)]
    require(not missing, "缺少真实待处理项，请匹配以下事项及其确认范围：" + stable_json([p.model_dump(mode="json") for p in missing]))
    if not partial:
        unexpected = [p for p in result.pending_items if not any(pending_covers(ctx, expected, p) for expected in required)]
        require(not unexpected, "待办没有未解决的工具证据或已经确认，请移除这些事项后重新finish：" + stable_json([p.model_dump(mode="json") for p in unexpected]))
    if partial:
        for aid in set(ctx.request.asset_ids) - set(ids):
            require((aid, "unprocessed", None, ()) in actual_signatures, "部分结果缺少未处理素材")
    else:
        require(result.status == ("needs_attention" if result.pending_items else "completed"), "整体状态与待办不一致")
