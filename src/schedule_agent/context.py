from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .schemas import Confirmation, RunRequest


@dataclass
class RuntimeContext:
    request: RunRequest
    db_path: Path = Path("data/app.db")
    rules_path: Path = Path("data/review_rules.json")
    preset_answers: list[Confirmation] = field(default_factory=list)
    reads: dict[str, list[dict]] = field(default_factory=dict)
    checks: dict[str, dict] = field(default_factory=dict)
    slots: list[dict] = field(default_factory=list)
    confirmations: list[Confirmation] = field(default_factory=list)
    questions: list[dict] = field(default_factory=list)
    saves: list[dict] = field(default_factory=list)
    save_attempts: int = 0
    errors: list[dict] = field(default_factory=list)
    rules_fingerprint: str | None = None

    def __post_init__(self):
        self.confirmations = list(self.request.confirmations)

    def observe(self, name: str, args: dict, observation: dict[str, Any]):
        if not observation["ok"]:
            self.errors.append({"action": name, "args": args, **observation["error"]})
            return
        data = observation["data"]
        if name in ("read_asset", "check_rules") and "rules_fingerprint" in data:
            self.rules_fingerprint = data["rules_fingerprint"]
        if name == "read_asset":
            self.reads.setdefault(args["asset_id"], []).append(data)
        elif name == "check_rules":
            self.checks[args["asset_id"]] = data
        elif name == "query_slots":
            self.slots.append(data)
        elif name == "request_confirmation":
            self.questions.append(data)
            if data.get("confirmation") is not None:
                self.confirmations.append(Confirmation.model_validate(data["confirmation"]))
        elif name == "save_draft":
            self.saves.append(data)
