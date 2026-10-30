"""Validate rule configuration and fingerprint the actual content, not only its label."""
import hashlib
import json
from typing import Literal

from pydantic import Field, model_validator

from .schemas import StrictModel
from .storage import BusinessError


class ReviewRules(StrictModel):
    version: str = Field(min_length=1)
    required_fields: list[Literal["title", "copyright_status", "content", "music_authorized", "manual_review_required"]] = Field(min_length=1)
    prohibited_words: list[str]
    copyright_required: str = Field(min_length=1)
    risk_actions: dict[str, str]
    risk_reasons: dict[str, str]

    @model_validator(mode="after")
    def policy(self):
        if self.risk_actions != {"none": "allow", "low": "pending_confirmation", "high": "block"}:
            raise ValueError("风险处理方式不能绕过安全边界")
        codes = {"prohibited_word", "unauthorized_music", "copyright_unlicensed", "manual_review"}
        if not codes <= self.risk_reasons.keys() or any(not self.risk_reasons[c].strip() for c in codes):
            raise ValueError("缺少风险原因")
        if any(not word.strip() for word in self.prohibited_words):
            raise ValueError("禁用词不能为空")
        return self


def load_rules(ctx):
    try:
        rules = ReviewRules.model_validate_json(ctx.rules_path.read_text(encoding="utf-8")).model_dump()
    except (OSError, ValueError, TypeError) as exc:
        ctx.rules_fingerprint = "unavailable"
        raise BusinessError("RuleDataError", "审核规则不可读取或结构无效") from exc
    canonical = json.dumps(rules, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    ctx.rules_fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return rules
