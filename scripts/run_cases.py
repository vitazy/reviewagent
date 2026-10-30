"""Execute real local cases, assert business outcomes, and generate an evidence index."""
import argparse
import json
import os
import shutil
from pathlib import Path

from dotenv import load_dotenv

from schedule_agent.cli import execute_case
from schedule_agent.llm import OpenAICompatibleLLM, normalize_provider
from schedule_agent.schemas import CaseSpec
from schedule_agent.storage import connection, seed_db

ORDER = ["normal", "missing_info", "rule_risk", "slot_conflict", "slot_conflict_hard",
         "duplicate", "save_failure", "slot_swap", "low_risk", "hard_confirmed"]
EXPECTED = {
    "normal": "approved / saved / 原时间 / 无待办",
    "missing_info": "needs_info / not_saved / 已补查",
    "rule_risk": "blocked / not_saved / 保留风险",
    "slot_conflict": "19:00 / saved / 待确认",
    "slot_conflict_hard": "不改hard时间 / not_saved / 待确认",
    "duplicate": "duplicate / 原ID / 同库仅一条",
    "save_failure": "两次保存失败 / failed / 无新增草稿",
    "slot_swap": "同一18:00输入 / 建议20:00 / saved",
    "low_risk": "低风险 / saved / 待人工复核",
    "hard_confirmed": "精确确认19:00 / saved / 保留改时标记",
}


def assert_outcome(name, result, rows, first_id):
    assert result.status in ("completed", "needs_attention"), result.status
    item = result.items[0]
    if name == "missing_info":
        assert (item.review_status, result.draft_status, item.suggested_time) == ("needs_info", "not_saved", None)
    elif name == "rule_risk":
        assert item.review_status == "blocked" and item.risk_reasons and result.draft_status == "not_saved"
    elif name == "slot_conflict_hard":
        assert item.suggested_time is None and item.requested_time.hour == 18 and result.draft_status == "not_saved"
    elif name == "save_failure":
        assert result.draft_status == "failed" and result.draft_id is None and rows == 0
    elif name == "duplicate":
        assert result.draft_status == "duplicate" and result.draft_id == first_id and rows == 1
    else:
        assert result.draft_status == "saved" and result.draft_id and rows == 1
        assert item.review_status == "approved"
    if name in ("slot_conflict", "duplicate", "slot_swap", "hard_confirmed"):
        assert item.suggested_time.hour == (20 if name == "slot_swap" else 19)
        assert item.requested_time.hour == 18 and item.needs_confirmation
    if name == "low_risk":
        assert item.needs_confirmation and any(p.kind == "risk_confirmation" for p in result.pending_items)
    if name in ("normal", "hard_confirmed"):
        assert result.status == "completed" and not result.pending_items


def write_index():
    lines = ["# 用例实际结果", "", "由 scripts/run_cases.py 根据实际运行生成。Mock 只验证流程，不证明模型的决策效果。", ""]
    for provider in ("mock", "real"):
        lines += [f"## {provider}", ""]
        report_path = Path(f"examples/run_report_{provider}.json")
        if not report_path.exists():
            lines += ["待真实模型运行（无对应运行记录）。" if provider == "real" else "待运行。", ""]
            continue
        report = json.loads(report_path.read_text())
        lines += ["| 用例 | 预期验收点 | 实际 | 证据 |", "| --- | --- | --- | --- |"]
        for row in report:
            name = row["case_id"]
            evidence = (f"[输入](cases/{name}.json) · [输出](outputs/{name}_{provider}.json) · "
                        f"[Trace](traces/{name}_{provider}.jsonl)") if row["passed"] else "检查错误记录；不标记通过"
            lines.append(f'| {name} | {EXPECTED.get(name, "结构与结束状态")} | {row["actual"]} | {evidence} |')
        lines.append("")
    if Path("examples/followup/report.json").exists():
        lines += ["批量、规则变化和接口契约扩展见[跟进结果](followup/results.md)。", ""]
    Path("examples/results.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    load_dotenv(override=False)
    parser = argparse.ArgumentParser(description="执行并核验本地业务用例，支持选择性复跑")
    parser.add_argument("--cases", nargs="+", choices=ORDER)
    args = parser.parse_args()
    provider = normalize_provider(os.getenv("LLM_PROVIDER", "mock"))
    if provider == "real":
        OpenAICompatibleLLM()  # Fail before touching evidence if configuration is absent.
    reports = []
    first_id = None
    dbroot = Path("examples/.run_db") / provider
    paths = sorted(Path("examples/cases").glob("*.json"), key=lambda p: ORDER.index(p.stem) if p.stem in ORDER else 999)
    if args.cases:
        selected = set(args.cases)
        if selected & {"duplicate", "slot_conflict"}:
            selected.update(("slot_conflict", "duplicate"))
        paths = [p for p in paths if p.stem in selected]
    for path in paths:
        case = CaseSpec.model_validate_json(path.read_text())
        name = case.case_id
        db = dbroot / ("slot_conflict.db" if name == "duplicate" else f"{name}.db")
        try:
            existing = [Path(f"examples/{folder}/{name}_{provider}.{ext}") for folder, ext in (("outputs", "json"), ("traces", "jsonl"))]
            if any(p.exists() for p in existing):
                history_root = Path("examples/history") / provider / name
                number = 1
                while (history_root / str(number)).exists():
                    number += 1
                target = history_root / str(number)
                target.mkdir(parents=True)
                for previous in existing:
                    if previous.exists():
                        shutil.copy2(previous, target / previous.name)
            if name != "duplicate":
                seed_db(db, case.fixture, reset=True)
            result = execute_case(case, db, provider=provider,
                        faults="save_draft:1,save_draft:2" if name == "save_failure" else "",
                        max_steps=int(os.getenv("MAX_STEPS", "12")), max_tool_calls=int(os.getenv("MAX_TOOL_CALLS", "12")))
            with connection(db) as connection_:
                rows = connection_.execute("SELECT COUNT(*) FROM drafts").fetchone()[0]
            assert_outcome(name, result, rows, first_id)
            if name == "slot_conflict":
                first_id = result.draft_id
            trace = [json.loads(line) for line in Path(f"examples/traces/{name}_{provider}.jsonl").read_text().splitlines()]
            if name == "missing_info":
                assert sum(r["action"] == "read_asset" for r in trace) >= 2
            if name == "save_failure":
                assert sum(r["action"] == "save_draft" and '"type":"InjectedFailure"' in r["observation_summary"] for r in trace) == 2
            actual = f'PASS：{result.items[0].review_status} / {result.draft_status} / {result.status}；drafts={rows}，steps={len(trace)}'
            reports.append({"case_id": name, "provider": provider, "passed": True, "actual": actual})
        except Exception as exc:
            # Do not print model configuration or authentication details.
            reports.append({"case_id": name, "provider": provider, "passed": False,
                            "actual": f"FAIL：{type(exc).__name__}"})
        print(f'{name}: {reports[-1]["actual"]}')
    report_path = Path(f"examples/run_report_{provider}.json")
    if args.cases and report_path.exists():
        merged = {r["case_id"]: r for r in json.loads(report_path.read_text())}
        merged.update({r["case_id"]: r for r in reports})
        report_rows = sorted(merged.values(), key=lambda r: ORDER.index(r["case_id"]))
    else:
        report_rows = reports
    report_path.write_text(json.dumps(report_rows, ensure_ascii=False, indent=2) + "\n")
    write_index()
    return 0 if reports and all(r["passed"] for r in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
