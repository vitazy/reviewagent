from __future__ import annotations

import json

from .context import RuntimeContext
from .guards import build_result, validate_result
from .prompts import SYSTEM_PROMPT
from .schemas import AgentResult
from .tools import ToolExecutor, failure, tool_schemas
from .trace import TraceWriter


def run_agent(ctx: RuntimeContext, llm, trace: TraceWriter, *, max_steps=12, max_tool_calls=12, faults="") -> AgentResult:
    if max_steps < 1 or max_tool_calls < 1:
        raise ValueError("预算必须为正整数")
    executor = ToolExecutor(ctx, faults)
    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps({"request": ctx.request.model_dump(mode="json")}, ensure_ascii=False)}]
    calls_used = 0
    for step in range(1, max_steps + 1):
        if calls_used >= max_tool_calls:
            break
        try:
            response = llm.complete(messages, tool_schemas())
        except Exception as exc:
            observation = failure("ModelError", f"模型调用失败（{type(exc).__name__}），未获得下一步动作")
            trace.add(step, "model_error", {}, observation)
            result = build_result(ctx, "incomplete_model_error", "模型接口调用失败，保留已完成部分，需重新运行")
            validate_result(ctx, result, partial=True)
            trace.close("model_error")
            return result
        if not isinstance(response, dict):
            response = {}
        calls = response.get("tool_calls") or []
        valid_calls = isinstance(calls, list) and all(
            isinstance(call, dict) and isinstance(call.get("id"), str) and bool(call["id"])
            and isinstance(call.get("function"), dict)
            and isinstance(call["function"].get("name"), str)
            and isinstance(call["function"].get("arguments"), str) for call in calls)
        if not valid_calls or len({call["id"] for call in calls}) != len(calls):
            observation = failure("InvalidResponse", "工具调用缺少唯一ID、函数名或字符串参数，请重新生成一个合法调用")
            messages.append({"role": "user", "content": json.dumps(observation, ensure_ascii=False)})
            trace.add(step, "invalid_response", {}, observation)
            continue
        messages.append({"role": "assistant", "content": response.get("content"), **({"tool_calls": calls} if calls else {})})
        if len(calls) != 1:
            observation = failure("InvalidResponse", "每轮必须产生且仅产生一个工具调用")
            trace.add(step, "invalid_response", {}, observation)
            if calls:
                for call in calls:
                    messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(observation, ensure_ascii=False)})
            else:
                messages.append({"role": "user", "content": json.dumps(observation, ensure_ascii=False)})
            continue
        calls_used += 1
        call = calls[0]
        name = call.get("function", {}).get("name", "unknown")
        try:
            args = json.loads(call["function"]["arguments"])
            if not isinstance(args, dict):
                raise ValueError("arguments必须为对象")
        except (ValueError, KeyError, TypeError):
            args = {}
            observation = failure("InvalidArguments", "工具参数必须为有效JSON对象")
        else:
            observation = executor.execute(name, args)
            args = executor.last_args
        trace.add(step, name, args, observation)
        messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(observation, ensure_ascii=False)})
        if name == "finish" and observation["ok"]:
            result = AgentResult.model_validate(observation["data"])
            trace.close()
            return result
    budget = "MAX_TOOL_CALLS" if calls_used >= max_tool_calls else "MAX_STEPS"
    result = build_result(ctx, "incomplete_step_limit", f"{budget}预算耗尽，未完成项需继续处理")
    validate_result(ctx, result, partial=True)
    trace.close("budget_exit")
    return result
