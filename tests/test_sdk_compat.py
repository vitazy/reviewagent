"""Real SDK + deterministic HTTP transport; no external model is called here."""
import json

import httpx
import pytest

pytest.importorskip("openai", reason="原生SDK契约测试需要requirements.txt中的openai依赖")

from schedule_agent.agent import run_agent
from schedule_agent.llm import OpenAICompatibleLLM
from schedule_agent.tools import tool_schemas
from schedule_agent.trace import TraceWriter


def completion(content=None, calls=None):
    return {"id": "synthetic-completion", "object": "chat.completion", "created": 0, "model": "contract-test",
            "choices": [{"index": 0, "finish_reason": "tool_calls" if calls else "stop",
                         "message": {"role": "assistant", "content": content, "tool_calls": calls}}]}


def call(name, arguments, id="call_contract"):
    return {"id": id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}


@pytest.fixture
def sdk_factory(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "https://contract.invalid/v1")
    monkeypatch.setenv("LLM_API_KEY", "synthetic-contract-key")
    monkeypatch.setenv("LLM_MODEL", "contract-test")
    monkeypatch.setenv("LLM_SEND_PARALLEL_TOOL_CALLS", "1")
    clients = []
    def make(handler):
        client = httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)
        clients.append(client)
        return OpenAICompatibleLLM(http_client=client)
    yield make
    for client in clients:
        client.close()


@pytest.mark.parametrize("send_flag", ["1", "0"])
@pytest.mark.parametrize("prefix", ["/v1", "/gateway/openai/v1"])
def test_standard_and_serial_only_gateway(sdk_factory, monkeypatch, send_flag, prefix):
    requests = []
    monkeypatch.setenv("LLM_SEND_PARALLEL_TOOL_CALLS", send_flag)
    monkeypatch.setenv("LLM_BASE_URL", "https://contract.invalid" + prefix)
    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        assert request.url.path == prefix + "/chat/completions"
        assert request.headers["authorization"] == "Bearer synthetic-contract-key"
        assert body["temperature"] == 0 and len(body["tools"]) == 6
        if send_flag == "1":
            assert body["parallel_tool_calls"] is False
        else:
            assert "parallel_tool_calls" not in body
        return httpx.Response(200, json=completion(calls=[call("read_asset", {"asset_id": "M01"})]))
    response = sdk_factory(handler).complete([{"role": "user", "content": "synthetic"}], tool_schemas())
    assert response["tool_calls"][0]["function"]["name"] == "read_asset" and len(requests) == 1


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422, 429, 500])
def test_http_errors_are_bounded_and_sanitized(sdk_factory, ctx_factory, tmp_path, status):
    count = 0
    def handler(request):
        nonlocal count
        count += 1
        return httpx.Response(status, json={"error": {"message": "sensitive-response-body", "type": "contract_error"}})
    trace_path = tmp_path / "http.jsonl"
    result = run_agent(ctx_factory(), sdk_factory(handler), TraceWriter(trace_path, "sdk-simulated", "http_error"))
    assert count == 1 and result.status == "incomplete_model_error" and result.draft_id is None
    assert "sensitive-response-body" not in trace_path.read_text()


def test_sdk_timeout_no_implicit_retry(sdk_factory, ctx_factory, tmp_path):
    count = 0
    def handler(request):
        nonlocal count
        count += 1
        raise httpx.ReadTimeout("synthetic timeout", request=request)
    result = run_agent(ctx_factory(), sdk_factory(handler), TraceWriter(tmp_path / "timeout.jsonl", "sdk-simulated", "timeout"))
    assert count == 1 and result.status == "incomplete_model_error"


@pytest.mark.parametrize("kind", ["text", "parallel", "bad_arguments", "missing_id", "duplicate_ids", "missing_function"])
def test_wire_protocol_does_not_bypass_runtime(sdk_factory, ctx_factory, tmp_path, kind):
    def handler(request):
        if kind == "text":
            payload = completion(content="done")
        elif kind == "parallel":
            payload = completion(calls=[call("read_asset", {"asset_id": "M01"}, "one"), call("check_rules", {"asset_id": "M01"}, "two")])
        elif kind == "bad_arguments":
            bad = call("read_asset", {})
            bad["function"]["arguments"] = "{"
            payload = completion(calls=[bad])
        elif kind == "duplicate_ids":
            payload = completion(calls=[call("read_asset", {"asset_id": "M01"}), call("check_rules", {"asset_id": "M01"})])
        else:
            bad = call("read_asset", {"asset_id": "M01"})
            bad.pop("id" if kind == "missing_id" else "function")
            payload = completion(calls=[bad])
        return httpx.Response(200, json=payload)
    ctx = ctx_factory()
    result = run_agent(ctx, sdk_factory(handler), TraceWriter(tmp_path / "protocol.jsonl", "sdk-simulated", kind), max_steps=2)
    assert result.status == "incomplete_step_limit" and not ctx.reads and not ctx.saves


def test_gateway_can_reject_optional_flag(sdk_factory, ctx_factory, tmp_path):
    def handler(request):
        assert "parallel_tool_calls" in json.loads(request.content)
        return httpx.Response(400, json={"error": {"message": "unsupported parallel_tool_calls"}})
    result = run_agent(ctx_factory(), sdk_factory(handler), TraceWriter(tmp_path / "unsupported.jsonl", "sdk-simulated", "unsupported"))
    assert result.status == "incomplete_model_error"
