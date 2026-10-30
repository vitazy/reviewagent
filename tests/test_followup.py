import json
from pathlib import Path

import pytest

from scripts.verify_followup import run_profile
from schedule_agent.guards import projected_item
from schedule_agent.tools import ToolExecutor


@pytest.mark.parametrize("name", ["long_batch_default", "long_batch_raised", "rules_changed_version",
                                  "rules_changed_content", "rules_invalid", "rules_changed_at_budget"])
def test_followup_profiles(tmp_path, name):
    report = run_profile(name, tmp_path / "db", tmp_path / "evidence")
    assert report["passed"]
    assert (tmp_path / "evidence/outputs" / f"{name}_mock.json").is_file()


@pytest.mark.parametrize("name", ["save_draft", "finish"])
def test_rules_changed_before_effect_or_finish(ctx_factory, tmp_path, name):
    ctx = ctx_factory()
    rules = tmp_path / "rules.json"
    rules.write_text(Path("data/review_rules.json").read_text())
    ctx.rules_path = rules
    tools = ToolExecutor(ctx)
    tools.execute("read_asset", {"asset_id": "M01"})
    tools.execute("check_rules", {"asset_id": "M01"})
    tools.execute("query_slots", {"channel": "video", "date": "2026-10-30", "around_time": "2026-10-30T19:00:00+08:00"})
    item = projected_item(ctx, "M01")
    from schedule_agent.guards import build_result
    result = build_result(ctx)
    updated = json.loads(rules.read_text())
    updated["prohibited_words"].append("原创")  # Same version label, different meaning.
    rules.write_text(json.dumps(updated, ensure_ascii=False))
    args = {"items": [item.model_dump(mode="json")]} if name == "save_draft" else {"result": result.model_dump(mode="json")}
    observation = tools.execute(name, args)
    assert observation["error"]["type"] == "StaleReview" and ctx.save_attempts == 0


@pytest.mark.parametrize("mutation", [
    lambda r: r.update(prohibited_words="string is not a word list"),
    lambda r: r.update(required_fields=["unknown_field"]),
    lambda r: r.update(risk_actions={"high": "allow"}),
    lambda r: r.update(risk_reasons={}),
    lambda r: r.update(prohibited_words=[""]),
])
def test_invalid_rules_are_observations(ctx_factory, tmp_path, mutation):
    ctx = ctx_factory()
    rules = json.loads(Path("data/review_rules.json").read_text())
    mutation(rules)
    ctx.rules_path = tmp_path / "invalid.json"
    ctx.rules_path.write_text(json.dumps(rules))
    observation = ToolExecutor(ctx).execute("check_rules", {"asset_id": "M01"})
    assert observation["error"]["type"] == "RuleDataError"
