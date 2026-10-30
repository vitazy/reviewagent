import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import ValidationError

from .agent import run_agent
from .context import RuntimeContext
from .llm import MockLLM, OpenAICompatibleLLM, normalize_provider
from .schemas import CaseSpec
from .tools import FaultInjector
from .trace import TraceWriter


def execute_case(case: CaseSpec, db: Path, *, provider="mock", output_root=Path("examples"),
                 faults="", max_steps=12, max_tool_calls=12):
    provider = normalize_provider(provider)
    if not db.is_file():
        raise ValueError("数据库不存在，请先运行scripts/seed_db.py；CLI不会隐式清空或创建数据")
    if max_steps < 1 or max_tool_calls < 1:
        raise ValueError("步数与工具预算必须为正整数")
    FaultInjector(faults)
    llm = MockLLM() if provider == "mock" else OpenAICompatibleLLM()
    ctx = RuntimeContext(case.request, db_path=db, preset_answers=case.preset_answers)
    run_id = f"{case.case_id}_{provider}"
    trace = TraceWriter(output_root / "traces" / f"{run_id}.jsonl", provider, case.case_id)
    try:
        result = run_agent(ctx, llm, trace, max_steps=max_steps, max_tool_calls=max_tool_calls, faults=faults)
    finally:
        if not trace.stream.closed:
            trace.close("runtime_error")
    output = output_root / "outputs" / f"{run_id}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return result


def main():
    load_dotenv(override=False)
    parser = argparse.ArgumentParser(description="素材审核与排期草稿Agent")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--case", type=Path, required=True)
    run.add_argument("--db", type=Path, default=Path("data/app.db"))
    run.add_argument("--provider", type=normalize_provider, choices=["mock", "real"], default=os.getenv("LLM_PROVIDER", "mock"))
    run.add_argument("--faults", default=os.getenv("FAULTS", ""))
    run.add_argument("--max-steps", type=int, default=os.getenv("MAX_STEPS", "12"))
    run.add_argument("--max-tool-calls", type=int, default=os.getenv("MAX_TOOL_CALLS", "12"))
    run.add_argument("--output-root", type=Path, default=Path("examples"))
    args = parser.parse_args()
    try:
        case = CaseSpec.model_validate_json(args.case.read_text(encoding="utf-8"))
        result = execute_case(case, args.db, provider=args.provider, output_root=args.output_root,
                              faults=args.faults, max_steps=args.max_steps, max_tool_calls=args.max_tool_calls)
        print(result.model_dump_json(indent=2))
        return 3 if result.status.startswith("incomplete_") else 0
    except (ValueError, OSError, ValidationError):
        print(json.dumps({"ok": False, "error": {"type": "ConfigurationError", "message":
              "输入、文件或配置无效；请检查case格式、数据库、预算、故障参数及真实模型配置"}}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
