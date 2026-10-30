"""Reproducible offline follow-up: larger requests and rules changing during a run."""
import json
from pathlib import Path

from schedule_agent.agent import run_agent
from schedule_agent.context import RuntimeContext
from schedule_agent.llm import MockLLM
from schedule_agent.schemas import CaseSpec
from schedule_agent.storage import connection, seed_db
from schedule_agent.trace import TraceWriter

ROOT = Path("examples/followup")


def long_case(case_id="long_batch_raised"):
    ids = [f"B{i:02}" for i in range(1, 17)]
    return CaseSpec(case_id=case_id, request={"asset_ids": ids, "channel": "video",
        "requested_times": {aid: {"time": "2026-10-30T08:00:00+08:00", "type": "soft"} for aid in ids}})


def prepare_long_db(path):
    seed_db(path, reset=True)
    with connection(path) as db:
        for aid in long_case().request.asset_ids:
            db.execute("INSERT INTO assets SELECT ?, title, copyright_status, content, music_authorized, manual_review_required, revision FROM assets WHERE asset_id='M01'", (aid,))
        db.commit()


class ChangingRules(MockLLM):
    """An external fixture changes rules; the policy still selects tools from observations."""
    def __init__(self, path, mode):
        self.path = path
        self.mode = mode
        self.changed = False

    def complete(self, messages, tools):
        response = super().complete(messages, tools)
        trigger = "query_slots" if self.mode == "budget" else "save_draft"
        if not self.changed and response["tool_calls"][0]["function"]["name"] == trigger:
            rules = json.loads(self.path.read_text())
            rules["prohibited_words"].append("原创")
            if self.mode == "version":
                rules["version"] = "synthetic-v2"
            self.path.write_text("{" if self.mode == "invalid" else json.dumps(rules, ensure_ascii=False))
            self.changed = True
        return response


def run_profile(name, work, output_root=ROOT):
    work.mkdir(parents=True, exist_ok=True)
    db = work / f"{name}.db"
    rules = work / f"{name}_rules.json"
    rules.write_text(Path("data/review_rules.json").read_text())
    if name.startswith("long_batch"):
        case = long_case(name)
        prepare_long_db(db)
        model = MockLLM()
    else:
        source = json.loads(Path("examples/cases/normal.json").read_text())
        source["case_id"] = name
        case = CaseSpec.model_validate(source)
        seed_db(db, reset=True)
        mode = {"rules_changed_version": "version", "rules_changed_content": "content", "rules_invalid": "invalid",
                "rules_changed_at_budget": "budget"}[name]
        model = ChangingRules(rules, mode)
    ctx = RuntimeContext(case.request, db_path=db, rules_path=rules)
    budget = 48 if name == "long_batch_raised" else 12
    if name == "rules_changed_at_budget":
        budget = 3
    trace_path = output_root / "traces" / f"{name}_mock.jsonl"
    trace = TraceWriter(trace_path, "mock", name)
    result = run_agent(ctx, model, trace, max_steps=budget, max_tool_calls=budget)
    rows = [json.loads(line) for line in trace_path.read_text().splitlines()]
    with connection(db) as conn:
        drafts = conn.execute("SELECT COUNT(*) FROM drafts").fetchone()[0]
    if name == "long_batch_raised":
        assert result.draft_status == "saved" and drafts == 1 and len(result.items) == 16
        times = [i.suggested_time for i in result.items if i.suggested_time]
        assert len(times) == len(set(times)) == 15
        assert any(p.kind == "slot_unavailable" for p in result.pending_items)
    elif name.startswith("long_batch") or name in ("rules_invalid", "rules_changed_at_budget"):
        assert result.status == "incomplete_step_limit" and result.draft_status == "not_saved" and drafts == 0
        assert any(p.kind == "unprocessed" for p in result.pending_items)
    else:
        assert result.items[0].review_status == "blocked" and result.draft_status == "not_saved" and drafts == 0
        assert any("StaleReview" in r["observation_summary"] for r in rows)
        assert sum(r["action"] == "check_rules" for r in rows) == 2
    for sub, content, suffix in (("cases", case.model_dump_json(indent=2), "json"),
                                  ("outputs", result.model_dump_json(indent=2), "json")):
        target = output_root / sub / f"{name}{'_mock' if sub == 'outputs' else ''}.{suffix}"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content + "\n")
    return {"case_id": name, "provider": "mock", "passed": True, "status": result.status,
            "draft_status": result.draft_status, "steps": len(rows), "items": len(result.items), "draft_rows": drafts}


def main():
    profiles = ["long_batch_default", "long_batch_raised", "rules_changed_version", "rules_changed_content", "rules_invalid", "rules_changed_at_budget"]
    report = []
    for name in profiles:
        row = run_profile(name, Path("examples/.run_db/followup"))
        report.append(row)
        print(json.dumps(row, ensure_ascii=False))
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
