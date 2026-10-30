"""Live check of the configured gateway without its optional parallel-call parameter."""
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from schedule_agent.cli import execute_case
from schedule_agent.schemas import CaseSpec
from schedule_agent.storage import connection, seed_db


def main():
    load_dotenv(override=False)
    os.environ["LLM_SEND_PARALLEL_TOOL_CALLS"] = "0"
    source = json.loads(Path("examples/cases/normal.json").read_text())
    source["case_id"] = "normal_serial_gateway"
    case = CaseSpec.model_validate(source)
    db = Path("examples/.run_db/followup/serial_gateway.db")
    seed_db(db, reset=True)
    root = Path("examples/followup")
    (root / "cases").mkdir(parents=True, exist_ok=True)
    (root / "cases/normal_serial_gateway.json").write_text(case.model_dump_json(indent=2) + "\n")
    result = execute_case(case, db, provider="real", output_root=root)
    assert result.status == "completed" and result.draft_status == "saved"
    with connection(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM drafts").fetchone()[0] == 1
    rows = (root / "traces/normal_serial_gateway_real.jsonl").read_text().splitlines()
    report = {"case_id": case.case_id, "provider": "real", "passed": True,
              "profile": "optional_parallel_parameter_omitted", "steps": len(rows),
              "status": result.status, "draft_status": result.draft_status}
    (root / "serial_gateway_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
