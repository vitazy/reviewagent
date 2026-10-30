from __future__ import annotations

import json
import os

from .context import RuntimeContext
from .guards import build_result, confirmed, projected_item, review_state, slot_available
from .schemas import RunRequest


def tool_message(name: str, args: dict, sequence: int = 1):
    return {"role": "assistant", "content": None, "tool_calls": [{"id": f"call_{sequence}",
            "type": "function", "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}]}


def normalize_provider(value: str) -> str:
    if value == "mock":
        return "mock"
    if value in ("real", "openai"):
        return "real"
    raise ValueError("LLM_PROVIDER必须是mock、real或openai")


class OpenAICompatibleLLM:
    provider = "real"

    def __init__(self, *, http_client=None):
        base_url = os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL")
        api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
        if not all((base_url, api_key, os.getenv("LLM_MODEL"))):
            raise ValueError("真实模型需要LLM_BASE_URL/OPENAI_BASE_URL、LLM_API_KEY/OPENAI_API_KEY及LLM_MODEL；不会自动切换Mock")
        timeout = float(os.getenv("LLM_TIMEOUT", "30"))
        if not 0 < timeout <= 300:
            raise ValueError("LLM_TIMEOUT必须大于0且不超过300秒")
        self.model = os.environ["LLM_MODEL"]
        flag = os.getenv("LLM_SEND_PARALLEL_TOOL_CALLS", "1").lower()
        if flag not in ("0", "1", "false", "true"):
            raise ValueError("LLM_SEND_PARALLEL_TOOL_CALLS必须为0/1或false/true")
        self.send_parallel_flag = flag in ("1", "true")
        try:
            from openai import OpenAI
            self.client = OpenAI(base_url=base_url, api_key=api_key,
                                 timeout=timeout, max_retries=0, **({"http_client": http_client} if http_client else {}))
        except ImportError as exc:
            raise ValueError("真实模型客户端依赖缺失，请安装requirements.txt（含SOCKS代理支持）") from exc

    def complete(self, messages, tools):
        response = self.client.chat.completions.create(model=self.model, messages=messages,
                    tools=tools, tool_choice="auto", temperature=0,
                    **({"parallel_tool_calls": False} if self.send_parallel_flag else {}))
        return response.choices[0].message.model_dump(exclude_none=True)


class MockLLM:
    """Offline policy over observations, not a trace replay or model quality proof."""

    provider = "mock"

    def complete(self, messages, tools):
        request = RunRequest.model_validate(json.loads(messages[1]["content"])["request"])
        view = RuntimeContext(request)
        calls = {}
        history = []
        for message in messages:
            if message["role"] == "assistant":
                for call in message.get("tool_calls", []):
                    try:
                        calls[call["id"]] = (call["function"]["name"], json.loads(call["function"]["arguments"]))
                    except (ValueError, KeyError):
                        continue
            elif message["role"] == "tool" and message["tool_call_id"] in calls:
                name, args = calls[message["tool_call_id"]]
                observation = json.loads(message["content"])
                history.append((name, args, observation))
                if name == "save_draft" and (observation["ok"] or observation["error"]["type"] in (
                        "InjectedFailure", "StorageError", "SlotUnavailable")):
                    view.save_attempts += 1
                view.observe(name, args, observation)
        sequence = len([m for m in messages if m["role"] == "assistant"]) + 1

        def choose(name, reason, **args):
            return tool_message(name, {**args, "reason": reason}, sequence)

        if history and not history[-1][2]["ok"] and history[-1][2]["error"]["type"] == "StaleReview":
            previous = history[-1][1]
            affected = previous.get("items", previous.get("result", {}).get("items", []))
            return choose("check_rules", "规则发生变化，重新审核", asset_id=affected[0]["asset_id"])

        if history and history[-1][0] == "save_draft" and not history[-1][2]["ok"] and history[-1][2]["error"]["type"] == "SlotUnavailable":
            req = request.requested_times[request.asset_ids[0]]
            return choose("query_slots", "保存前时段变化，重新查询", channel=request.channel,
                          date=req.time.date().isoformat(), around_time=req.time.isoformat())

        planned = []
        reserved = set()
        for aid in request.asset_ids:
            reads = view.reads.get(aid, [])
            check = view.checks.get(aid)
            if not reads:
                return choose("read_asset", "读取素材元数据", asset_id=aid)
            if not check or check.get("rules_fingerprint") != view.rules_fingerprint or reads[-1]["revision"] != check["revision"]:
                return choose("check_rules", "根据本地规则审核素材", asset_id=aid)
            state = review_state(check)
            if state == "needs_info" and len(reads) < 2:
                return choose("read_asset", "缺少必填字段，补查一次", asset_id=aid)
            if state != "approved":
                continue
            req = request.requested_times[aid]
            if not any(s["date"] == req.time.date().isoformat() for s in view.slots):
                return choose("query_slots", "查询请求时段及附近候选", channel=request.channel,
                              date=req.time.date().isoformat(), around_time=req.time.isoformat())
            if req.type == "hard" and not slot_available(view, req.time):
                candidates = [t for s in reversed(view.slots) for t in s["nearby_available"]]
                candidate = candidates[0] if candidates else None
                if candidate and not confirmed(view, aid, "time_change", candidate) and not any(
                        q["asset_id"] == aid and q["confirmation_type"] == "time_change" for q in view.questions):
                    return choose("request_confirmation", "硬性时间冲突，需精确授权", asset_id=aid,
                                  question=f"是否接受调整到{candidate}？", confirmation_type="time_change", proposed_time=candidate)
            item = projected_item(view, aid, reserved)
            if item and item.suggested_time:
                reserved.add(item.suggested_time)
                planned.append(item)
        if planned and not view.saves and view.save_attempts < 2:
            return choose("save_draft", "保存有证据支持的排期草稿" if not view.save_attempts else "观察到保存失败，重试一次",
                          items=[i.model_dump(mode="json") for i in planned], idempotency_key="auto")
        result = build_result(view)
        return choose("finish", "根据审核、确认和真实保存结果结束", result=result.model_dump(mode="json"))
