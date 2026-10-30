import json
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from schedule_agent.cli import execute_case
from schedule_agent.llm import OpenAICompatibleLLM, normalize_provider
from schedule_agent.schemas import CaseSpec, ToolObservation
from schedule_agent.tools import ARGUMENTS, FaultInjector, ToolExecutor


@pytest.mark.parametrize("mutation", [
    lambda r: r.update(asset_ids=["M01", "M01"]),
    lambda r: r["requested_times"].clear(),
    lambda r: r["requested_times"]["M01"].update(type="maybe"),
    lambda r: r["requested_times"]["M01"].update(time="2026-10-30T19:00:00"),
    lambda r: r["requested_times"]["M01"].update(time="2026-10-30T19:30:00+08:00"),
])
def test_invalid_input(mutation):
    data = json.loads(Path("examples/cases/normal.json").read_text())
    mutation(data["request"])
    with pytest.raises(ValidationError):
        CaseSpec.model_validate(data)


def test_unsafe_case_id():
    data = json.loads(Path("examples/cases/normal.json").read_text())
    data["case_id"] = "../../escape"
    with pytest.raises(ValidationError):
        CaseSpec.model_validate(data)


@pytest.mark.parametrize("text", ["save_draft:0", "save_draft:-1", "bad:1", "finish:1", "save_draft", "save_draft:x"])
def test_invalid_faults(text):
    with pytest.raises(ValueError):
        FaultInjector(text)


def test_faults_reset_per_run(ctx_factory):
    for _ in range(2):
        tools = ToolExecutor(ctx_factory(), "read_asset:1")
        assert not tools.execute("read_asset", {"asset_id": "M01"})["ok"]
        assert tools.execute("read_asset", {"asset_id": "M01"})["ok"]


def test_tool_errors_are_uniform(ctx_factory):
    tools = ToolExecutor(ctx_factory())
    for name, args in [("unknown", {}), ("read_asset", {}), ("read_asset", {"asset_id": "OUTSIDE"})]:
        observation = tools.execute(name, args)
        assert set(observation) == {"ok", "data", "error"}
        assert not observation["ok"] and observation["data"] is None
        ToolObservation.model_validate(observation)
    tools.ctx.db_path = Path("/tmp/nonexistent-parent-schedule-agent/db")
    assert not tools.execute("read_asset", {"asset_id": "M01"})["ok"]


def test_confirmation_scope_and_rejection(ctx_factory):
    from schedule_agent.schemas import Confirmation
    ctx = ctx_factory("slot_conflict_hard")
    ctx.preset_answers = [Confirmation(asset_id="M01", kind="time_change", accepted=False,
                                       proposed_time="2026-10-30T19:00:00+08:00")]
    tools = ToolExecutor(ctx)
    unscoped = tools.execute("request_confirmation", {"asset_id": "M01", "question": "同意吗"})
    assert unscoped["data"]["confirmation"] is None
    rejected = tools.execute("request_confirmation", {"asset_id": "M01", "question": "接受19点吗",
                 "confirmation_type": "time_change", "proposed_time": "2026-10-30T19:00:00+08:00"})
    assert rejected["data"]["status"] == "rejected" and not ctx.confirmations[-1].accepted


def test_provider_config_is_explicit(monkeypatch):
    for name in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValueError, match="不会自动切换"):
        OpenAICompatibleLLM()


@pytest.mark.parametrize("use_aliases", [False, True, "both"])
def test_real_adapter_sdk_contract_without_network(monkeypatch, use_aliases):
    seen = {}
    def create(**kwargs):
        seen["request"] = kwargs
        message = SimpleNamespace(model_dump=lambda **_: {"role": "assistant", "tool_calls": []})
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])
    def client(**kwargs):
        seen["client"] = kwargs
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=client))
    for name in ("LLM_BASE_URL", "LLM_API_KEY", "OPENAI_BASE_URL", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    prefix = "OPENAI" if use_aliases is True else "LLM"
    for name, value in ((f"{prefix}_BASE_URL", "https://example.invalid/v1"), (f"{prefix}_API_KEY", "synthetic-test-key"), ("LLM_MODEL", "test")):
        monkeypatch.setenv(name, value)
    if use_aliases == "both":
        monkeypatch.setenv("OPENAI_BASE_URL", "https://unused.invalid/v1")
        monkeypatch.setenv("OPENAI_API_KEY", "unused-synthetic-key")
    provider = OpenAICompatibleLLM()
    provider.complete([], [])
    assert seen["client"]["max_retries"] == 0 and seen["client"]["timeout"] == 30
    assert seen["client"]["api_key"] == "synthetic-test-key"
    assert seen["client"]["base_url"] == "https://example.invalid/v1"
    assert seen["request"]["temperature"] == 0 and seen["request"]["parallel_tool_calls"] is False


@pytest.mark.parametrize("value,expected", [("mock", "mock"), ("real", "real"), ("openai", "real")])
def test_provider_alias(value, expected):
    assert normalize_provider(value) == expected


def test_invalid_provider_rejected():
    with pytest.raises(ValueError):
        normalize_provider("unknown")


def test_missing_client_dependency_is_configuration_error(monkeypatch):
    for name, value in (("LLM_BASE_URL", "https://example.invalid/v1"),
                        ("LLM_API_KEY", "synthetic-test-key"), ("LLM_MODEL", "test")):
        monkeypatch.setenv(name, value)
    def unavailable(**kwargs):
        raise ImportError("SOCKS dependency unavailable")
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=unavailable))
    with pytest.raises(ValueError, match="依赖缺失"):
        OpenAICompatibleLLM()


def test_cli_provider_outputs_separate(ctx_factory, tmp_path):
    case = CaseSpec.model_validate_json(Path("examples/cases/normal.json").read_text())
    ctx = ctx_factory()
    result = execute_case(case, ctx.db_path, output_root=tmp_path)
    assert result.draft_status == "saved"
    assert (tmp_path / "outputs/normal_mock.json").is_file()
    assert not (tmp_path / "outputs/normal_real.json").exists()
    assert set(ARGUMENTS) == {"read_asset", "check_rules", "query_slots", "request_confirmation", "save_draft", "finish"}
