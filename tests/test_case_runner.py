import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def test_selected_cases_keep_duplicate_dependency_reports_and_history(tmp_path):
    root = Path(__file__).resolve().parents[1]
    shutil.copytree(root / "data", tmp_path / "data", ignore=shutil.ignore_patterns("*.db*"))
    shutil.copytree(root / "examples/cases", tmp_path / "examples/cases")
    env = {**os.environ, "LLM_PROVIDER": "mock", "PYTHONPATH": str(root / "src")}
    def run(*names):
        result = subprocess.run([sys.executable, str(root / "scripts/run_cases.py"), "--cases", *names],
                                cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stdout + result.stderr
        return json.loads((tmp_path / "examples/run_report_mock.json").read_text())
    rows = run("slot_conflict")
    assert [r["case_id"] for r in rows] == ["slot_conflict", "duplicate"]
    rows = run("normal")
    assert {r["case_id"] for r in rows} == {"normal", "slot_conflict", "duplicate"}
    previous = json.loads((tmp_path / "examples/outputs/normal_mock.json").read_text())
    run("normal")
    archived = tmp_path / "examples/history/mock/normal/1/normal_mock.json"
    assert json.loads(archived.read_text()) == previous
