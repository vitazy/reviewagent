import json
from pathlib import Path


class TraceWriter:
    def __init__(self, path: Path, provider: str, source_case_id: str):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = path.open("w", encoding="utf-8")
        self.provider = provider
        self.source_case_id = source_case_id
        self.pending = None

    def add(self, step: int, action: str, args: dict, observation: dict):
        self.flush(action)
        self.pending = {"step": step, "action": action, "args": args,
                        "observation_summary": json.dumps(observation, ensure_ascii=False, separators=(",", ":"))[:200],
                        "next_action": None, "decision_note": args.get("reason", "") if isinstance(args, dict) else "",
                        "provider": self.provider, "source_case_id": self.source_case_id}

    def flush(self, next_action="end"):
        if self.pending is not None:
            self.pending["next_action"] = next_action
            self.stream.write(json.dumps(self.pending, ensure_ascii=False) + "\n")
            self.stream.flush()
            self.pending = None

    def close(self, next_action="end"):
        self.flush(next_action)
        self.stream.close()
