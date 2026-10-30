from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime

import pytest

from schedule_agent.guards import (build_result, canonical_items, canonical_request, idempotency_key,
                                   projected_item, validate_candidates, validate_result)
from schedule_agent.schemas import Confirmation, utc
from schedule_agent.storage import BusinessError, connection, persist
from schedule_agent.tools import ToolExecutor


def prepared(ctx):
    tools = ToolExecutor(ctx)
    aid = ctx.request.asset_ids[0]
    req = ctx.request.requested_times[aid]
    assert tools.execute("read_asset", {"asset_id": aid})["ok"]
    assert tools.execute("check_rules", {"asset_id": aid})["ok"]
    assert tools.execute("query_slots", {"channel": ctx.request.channel, "date": req.time.date().isoformat(),
                                         "around_time": req.time.isoformat()})["ok"]
    return tools, projected_item(ctx, aid)


def test_change_requires_marker(ctx_factory):
    ctx = ctx_factory("slot_conflict")
    _, item = prepared(ctx)
    item.needs_confirmation = False
    with pytest.raises(BusinessError, match="改时"):
        validate_candidates(ctx, [item])


@pytest.mark.parametrize("confirmation", [None,
    {"asset_id": "M01", "kind": "time_change", "accepted": False, "proposed_time": "2026-10-30T19:00:00+08:00"},
    {"asset_id": "M01", "kind": "time_change", "accepted": True, "proposed_time": "2026-10-30T20:00:00+08:00"},
])
def test_hard_guard_before_save_and_finish(ctx_factory, confirmation):
    ctx = ctx_factory("slot_conflict_hard")
    tools, item = prepared(ctx)
    if confirmation:
        ctx.confirmations.append(Confirmation.model_validate(confirmation))
    item.suggested_time = datetime.fromisoformat("2026-10-30T19:00:00+08:00")
    item.needs_confirmation = True
    item.confirmation_reason = "用户已同意"  # Text is not authorization.
    observation = tools.execute("save_draft", {"items": [item.model_dump(mode="json")], "idempotency_key": "auto"})
    assert observation["error"]["type"] == "GuardViolation"
    with connection(ctx.db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM drafts").fetchone()[0] == 0
    result = build_result(ctx)
    result.items = [item]
    with pytest.raises(BusinessError, match="hard"):
        validate_result(ctx, result)


def test_exact_hard_confirmation_allows_save(ctx_factory):
    ctx = ctx_factory("slot_conflict_hard")
    ctx.confirmations.append(Confirmation(asset_id="M01", kind="time_change", accepted=True,
                                         proposed_time="2026-10-30T19:00:00+08:00"))
    tools, item = prepared(ctx)
    assert item.suggested_time.hour == 19 and item.needs_confirmation
    assert tools.execute("save_draft", {"items": [item.model_dump(mode="json")]})["ok"]


def test_fabricated_save_and_skipped_save_rejected(ctx_factory):
    ctx = ctx_factory()
    prepared(ctx)
    result = build_result(ctx)
    with pytest.raises(BusinessError, match="先尝试保存"):
        validate_result(ctx, result)
    result.draft_status, result.draft_id = "saved", "D-invented"
    with pytest.raises(BusinessError, match="真实工具"):
        validate_result(ctx, result)


def test_omitting_candidate_cannot_bypass_save(ctx_factory):
    ctx = ctx_factory()
    prepared(ctx)
    result = build_result(ctx)
    result.items[0].suggested_time = None
    from schedule_agent.guards import required_pending
    result.pending_items = required_pending(ctx, result.items)
    result.status = "needs_attention"
    with pytest.raises(BusinessError, match="省略建议"):
        validate_result(ctx, result)


@pytest.mark.parametrize("field", ["confirmation_reason", "risk_reasons", "pending_items"])
def test_nested_forbidden_words_rejected(ctx_factory, field):
    ctx = ctx_factory()
    tools, item = prepared(ctx)
    tools.execute("save_draft", {"items": [item.model_dump(mode="json")]})
    result = build_result(ctx)
    if field == "pending_items":
        from schedule_agent.schemas import PendingItem
        result.pending_items.append(PendingItem(kind="note", message="内容已上线"))
    else:
        setattr(result.items[0], field, ["内容已发布"] if field == "risk_reasons" else "内容已发布")
    with pytest.raises(BusinessError, match="发布表述"):
        validate_result(ctx, result)


def test_saved_content_cannot_drift(ctx_factory):
    ctx = ctx_factory("slot_conflict")
    tools, item = prepared(ctx)
    tools.execute("save_draft", {"items": [item.model_dump(mode="json")]})
    result = build_result(ctx)
    result.items[0].suggested_time = datetime.fromisoformat("2026-10-30T20:00:00+08:00")
    with pytest.raises(BusinessError, match="不一致"):
        validate_result(ctx, result)


def test_key_canonicalization(ctx_factory):
    ctx = ctx_factory("slot_conflict")
    tools, item = prepared(ctx)
    key = idempotency_key(ctx, [item])
    item.confirmation_reason = "另一种说明措辞"
    item.requested_time = item.requested_time.astimezone(__import__('datetime').timezone.utc)
    assert idempotency_key(ctx, [item]) == key
    item.suggested_time = datetime.fromisoformat("2026-10-30T20:00:00+08:00")
    assert idempotency_key(ctx, [item]) != key
    assert not tools.execute("save_draft", {"items": [item.model_dump(mode="json")], "idempotency_key": "wrong"})["ok"]


def test_key_asset_and_mapping_order(ctx_factory):
    from schedule_agent.schemas import CaseSpec
    from pathlib import Path
    case = CaseSpec.model_validate_json(Path("examples/cases/normal.json").read_text())
    case.request.asset_ids.append("M04")
    case.request.requested_times["M04"] = case.request.requested_times["M01"].model_copy()
    ctx = ctx_factory(case=case)
    tools, one = prepared(ctx)
    tools.execute("read_asset", {"asset_id": "M04"})
    tools.execute("check_rules", {"asset_id": "M04"})
    two = projected_item(ctx, "M04", {one.suggested_time})
    key = idempotency_key(ctx, [one, two])
    ctx.request.asset_ids.reverse()
    ctx.request.requested_times = dict(reversed(list(ctx.request.requested_times.items())))
    assert idempotency_key(ctx, [two, one]) == key


def test_slot_changed_between_query_and_save(ctx_factory):
    ctx = ctx_factory()
    tools, item = prepared(ctx)
    with connection(ctx.db_path) as db:
        db.execute("INSERT INTO schedule(channel,start_time_utc,asset_id) VALUES(?,?,?)",
                   (ctx.request.channel, utc(item.suggested_time), "OTHER"))
        db.commit()
    result = tools.execute("save_draft", {"items": [item.model_dump(mode="json")]})
    assert result["error"]["type"] == "SlotUnavailable"
    with connection(ctx.db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM drafts").fetchone()[0] == 0


def test_concurrent_duplicate_transaction(ctx_factory):
    ctx = ctx_factory()
    _, item = prepared(ctx)
    key = idempotency_key(ctx, [item])
    def save(_):
        return persist(ctx.db_path, key, canonical_request(ctx), canonical_items(ctx, [item]))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, range(2)))
    assert {r["draft_status"] for r in results} == {"saved", "duplicate"}
    assert len({r["draft_id"] for r in results}) == 1


def test_retry_cap_and_exception_envelope(ctx_factory):
    ctx = ctx_factory()
    _, item = prepared(ctx)
    tools = ToolExecutor(ctx, "save_draft:1,save_draft:2")
    args = {"items": [item.model_dump(mode="json")]}
    assert [tools.execute("save_draft", args)["error"]["type"] for _ in range(3)] == [
        "InjectedFailure", "InjectedFailure", "RetryLimitExceeded"]
    assert ctx.save_attempts == 2


def test_no_approval_without_rules_evidence(ctx_factory):
    ctx = ctx_factory()
    _, item = prepared(ctx)
    ctx.checks.clear()
    with pytest.raises(BusinessError, match="证据"):
        validate_candidates(ctx, [item])


def test_low_risk_cannot_erase_confirmation(ctx_factory):
    ctx = ctx_factory("low_risk")
    _, item = prepared(ctx)
    item.needs_confirmation = False
    with pytest.raises(BusinessError, match="低风险"):
        validate_candidates(ctx, [item])


def test_batch_conflict_is_rejected(ctx_factory):
    ctx = ctx_factory()
    _, item = prepared(ctx)
    copy = deepcopy(item)
    copy.asset_id = "M04"
    ctx.request.asset_ids.append("M04")
    ctx.request.requested_times["M04"] = ctx.request.requested_times["M01"].model_copy()
    tools = ToolExecutor(ctx)
    tools.execute("read_asset", {"asset_id": "M04"})
    tools.execute("check_rules", {"asset_id": "M04"})
    copy = projected_item(ctx, "M04")
    with pytest.raises(BusinessError, match="内部时段冲突"):
        validate_candidates(ctx, [item, copy])


def test_high_risk_pending_can_include_observed_codes(ctx_factory):
    ctx = ctx_factory("rule_risk")
    prepared(ctx)
    result = build_result(ctx)
    result.pending_items[0].risk_codes = ctx.checks["M03"]["risk_codes"]
    validate_result(ctx, result)
    result.pending_items[0].risk_codes = ["invented"]
    with pytest.raises(BusinessError, match="待处理项"):
        validate_result(ctx, result)


@pytest.mark.parametrize("time,valid", [("19:00", True), ("18:00", False), ("17:00", False)])
def test_hard_pending_candidate_must_have_availability_evidence(ctx_factory, time, valid):
    ctx = ctx_factory("slot_conflict_hard")
    prepared(ctx)
    result = build_result(ctx)
    result.pending_items[0].proposed_time = datetime.fromisoformat(f"2026-10-30T{time}:00+08:00")
    if valid:
        validate_result(ctx, result)
    else:
        with pytest.raises(BusinessError, match="待处理项"):
            validate_result(ctx, result)


def test_scoped_save_failure_pending_is_valid(ctx_factory):
    ctx = ctx_factory()
    _, item = prepared(ctx)
    tools = ToolExecutor(ctx, "save_draft:1,save_draft:2")
    for _ in range(2):
        tools.execute("save_draft", {"items": [item.model_dump(mode="json")]})
    result = build_result(ctx)
    result.pending_items[0].asset_id = "M01"
    validate_result(ctx, result)


def test_resolved_confirmation_cannot_be_pending_again(ctx_factory):
    from schedule_agent.schemas import PendingItem
    ctx = ctx_factory("slot_conflict_hard")
    ctx.confirmations.append(Confirmation(asset_id="M01", kind="time_change", accepted=True,
                                          proposed_time="2026-10-30T19:00:00+08:00"))
    tools, item = prepared(ctx)
    tools.execute("save_draft", {"items": [item.model_dump(mode="json")]})
    result = build_result(ctx)
    assert result.status == "completed" and item.needs_confirmation
    result.pending_items.append(PendingItem(asset_id="M01", kind="time_confirmation", message="再次确认",
                                             proposed_time=item.suggested_time))
    result.status = "needs_attention"
    with pytest.raises(BusinessError, match="已经确认"):
        validate_result(ctx, result)
