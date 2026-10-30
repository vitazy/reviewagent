import json
from pathlib import Path

import pytest

from schedule_agent.agent import run_agent
from schedule_agent.guards import build_result
from schedule_agent.llm import MockLLM, tool_message
from schedule_agent.schemas import CaseSpec
from schedule_agent.storage import connection
from schedule_agent.trace import TraceWriter


def execute(ctx, tmp_path, llm=None, **kwargs):
    trace_path = tmp_path / "trace.jsonl"
    trace = TraceWriter(trace_path, "mock", "test")
    result = run_agent(ctx, llm or MockLLM(), trace, **kwargs)
    return result, [json.loads(line) for line in trace_path.read_text().splitlines()]


@pytest.mark.parametrize("name,review,draft,hour", [
    ("normal", "approved", "saved", 19), ("missing_info", "needs_info", "not_saved", None),
    ("rule_risk", "blocked", "not_saved", None), ("slot_conflict", "approved", "saved", 19),
    ("slot_conflict_hard", "approved", "not_saved", None), ("slot_swap", "approved", "saved", 20),
    ("low_risk", "approved", "saved", 19), ("hard_confirmed", "approved", "saved", 19),
])
def test_business_paths(ctx_factory, tmp_path, name, review, draft, hour):
    ctx = ctx_factory(name)
    result, rows = execute(ctx, tmp_path)
    assert result.items[0].review_status == review
    assert result.draft_status == draft
    assert (result.items[0].suggested_time.hour if result.items[0].suggested_time else None) == hour
    assert rows[-1]["action"] == "finish" and rows[-1]["next_action"] == "end"
    assert all(len(r["observation_summary"]) <= 200 for r in rows)
    assert [r["next_action"] for r in rows[:-1]] == [r["action"] for r in rows[1:]]
    if name == "missing_info":
        assert sum(r["action"] == "read_asset" for r in rows) == 2
    if name in ("low_risk", "slot_conflict"):
        assert result.items[0].needs_confirmation and result.status == "needs_attention"
    if name == "hard_confirmed":
        assert result.items[0].needs_confirmation and result.status == "completed"


def test_duplicate_persists_one_row(ctx_factory, tmp_path):
    from schedule_agent.context import RuntimeContext
    ctx = ctx_factory("slot_conflict")
    first, _ = execute(ctx, tmp_path)
    duplicate = RuntimeContext(ctx.request, db_path=ctx.db_path)
    second, _ = execute(duplicate, tmp_path)
    assert second.draft_status == "duplicate" and second.draft_id == first.draft_id
    with connection(ctx.db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM drafts").fetchone()[0] == 1


@pytest.mark.parametrize("faults,draft,attempts", [
    ("save_draft:1", "saved", 2), ("save_draft:1,save_draft:2", "failed", 2),
    ("read_asset:1,check_rules:1,query_slots:1", "saved", 1),
])
def test_fault_recovery(ctx_factory, tmp_path, faults, draft, attempts):
    ctx = ctx_factory()
    result, rows = execute(ctx, tmp_path, faults=faults)
    assert result.draft_status == draft and ctx.save_attempts == attempts
    if draft == "failed":
        assert result.draft_id is None and result.status == "needs_attention"
        with connection(ctx.db_path) as db:
            assert db.execute("SELECT COUNT(*) FROM drafts").fetchone()[0] == 0


@pytest.mark.parametrize("kwargs,saved", [({"max_steps": 1}, False), ({"max_tool_calls": 1}, False),
                                          ({"max_steps": 4}, True)])
def test_budget_partial(ctx_factory, tmp_path, kwargs, saved):
    result, rows = execute(ctx_factory(), tmp_path, **kwargs)
    assert result.status == "incomplete_step_limit"
    assert bool(result.draft_id) is saved
    assert result.pending_items and rows[-1]["next_action"] == "budget_exit"
    if not saved:
        assert result.items == [] and any(p.kind == "unprocessed" for p in result.pending_items)


def test_finish_at_exact_limit(ctx_factory, tmp_path):
    result, rows = execute(ctx_factory(), tmp_path, max_steps=5, max_tool_calls=5)
    assert result.status == "completed" and len(rows) == 5


class BrokenModel:
    def complete(self, messages, tools):
        raise TimeoutError("provider details must not leak")


def test_model_error_partial(ctx_factory, tmp_path):
    result, rows = execute(ctx_factory(), tmp_path, BrokenModel())
    assert result.status == "incomplete_model_error" and result.items == []
    assert rows[-1]["action"] == "model_error"
    assert "provider details" not in json.dumps(rows)


def test_model_error_after_save_keeps_truth(ctx_factory, tmp_path):
    class FailsAfterSave(MockLLM):
        def complete(self, messages, tools):
            if len(messages) >= 10:
                raise TimeoutError()
            return super().complete(messages, tools)
    result, _ = execute(ctx_factory(), tmp_path, FailsAfterSave())
    assert result.status == "incomplete_model_error" and result.draft_status == "saved" and result.draft_id


def test_budget_after_save_and_further_query_keeps_saved_snapshot(ctx_factory, tmp_path):
    class QueryAfterSave(MockLLM):
        def complete(self, messages, tools):
            if len(messages) == 10:
                return tool_message("query_slots", {"channel": "video", "date": "2026-10-30",
                                    "around_time": "2026-10-30T20:00:00+08:00"}, 99)
            if len(messages) > 10:
                return {"role": "assistant", "content": "continue"}
            return super().complete(messages, tools)
    result, _ = execute(ctx_factory(), tmp_path, QueryAfterSave(), max_steps=6)
    assert result.status == "incomplete_step_limit" and result.draft_status == "saved"
    assert result.items[0].suggested_time.hour == 19


@pytest.mark.parametrize("response", [
    {"role": "assistant", "content": "done"},
    tool_message("unknown", {}),
    {"role": "assistant", "tool_calls": [{"id": "bad", "type": "function", "function": {"name": "read_asset", "arguments": "{"}}]},
    {"role": "assistant", "tool_calls": tool_message("read_asset", {"asset_id": "M01"})["tool_calls"] +
     tool_message("check_rules", {"asset_id": "M01"}, 2)["tool_calls"]},
])
def test_protocol_errors_are_bounded(ctx_factory, tmp_path, response):
    class InvalidModel:
        def complete(self, messages, tools):
            return response
    result, rows = execute(ctx_factory(), tmp_path, InvalidModel(), max_steps=2)
    assert result.status == "incomplete_step_limit" and len(rows) == 2
    assert not result.items and result.draft_status == "not_saved"


def test_finish_guard_error_is_observed_then_corrected(ctx_factory, tmp_path):
    class BadFinishOnce(MockLLM):
        changed = False
        def complete(self, messages, tools):
            response = super().complete(messages, tools)
            call = response["tool_calls"][0]
            if call["function"]["name"] == "finish" and not self.changed:
                args = json.loads(call["function"]["arguments"])
                args["result"]["items"][0]["needs_confirmation"] = False
                call["function"]["arguments"] = json.dumps(args)
                self.changed = True
            return response
    result, rows = execute(ctx_factory("slot_conflict"), tmp_path, BadFinishOnce())
    assert result.draft_status == "saved"
    assert sum(r["action"] == "finish" for r in rows) == 2
    assert "GuardViolation" in rows[-2]["observation_summary"]


def test_multiple_assets_allocate_different_slots(ctx_factory, tmp_path):
    case = CaseSpec.model_validate_json(Path("examples/cases/normal.json").read_text())
    case.request.asset_ids.append("M04")
    case.request.requested_times["M04"] = case.request.requested_times["M01"].model_copy()
    result, _ = execute(ctx_factory(case=case), tmp_path, max_steps=20, max_tool_calls=20)
    assert [i.suggested_time.hour for i in result.items] == [19, 20]
    assert result.draft_status == "saved"


def test_mixed_batch_only_saves_safe_asset(ctx_factory, tmp_path):
    case = CaseSpec.model_validate_json(Path("examples/cases/normal.json").read_text())
    case.request.asset_ids.append("M02")
    case.request.requested_times["M02"] = case.request.requested_times["M01"].model_copy()
    ctx = ctx_factory(case=case)
    result, _ = execute(ctx, tmp_path, max_steps=20, max_tool_calls=20)
    assert [i.review_status for i in result.items] == ["approved", "needs_info"]
    assert len(ctx.saves[-1]["items"]) == 1 and result.status == "needs_attention"
