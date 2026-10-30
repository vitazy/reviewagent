from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

BUSINESS_TZ = ZoneInfo("Asia/Shanghai")


def slot(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("时间必须包含时区")
    if value.minute or value.second or value.microsecond:
        raise ValueError("时间必须为整点")
    if not 2000 <= value.year <= 2100:
        raise ValueError("时间年份必须在2000至2100之间")
    return value.astimezone(BUSINESS_TZ)


def utc(value: datetime | str) -> str:
    dt = datetime.fromisoformat(value) if isinstance(value, str) else value
    return slot(dt).astimezone(timezone.utc).isoformat()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RequestedTime(StrictModel):
    time: datetime
    type: Literal["hard", "soft"]
    _time = field_validator("time")(slot)


class Confirmation(StrictModel):
    asset_id: str = Field(min_length=1)
    kind: Literal["time_change", "risk_ack"]
    accepted: bool
    proposed_time: datetime | None = None
    risk_codes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def scope(self):
        if self.kind == "time_change":
            if self.proposed_time is None or self.risk_codes:
                raise ValueError("时间确认必须绑定具体时间，不能包含风险代码")
            self.proposed_time = slot(self.proposed_time)
        elif not self.risk_codes or self.proposed_time is not None:
            raise ValueError("风险确认必须绑定非空风险代码")
        self.risk_codes = sorted(set(self.risk_codes))
        return self


class RunRequest(StrictModel):
    asset_ids: list[str] = Field(min_length=1)
    channel: str = Field(min_length=1)
    requested_times: dict[str, RequestedTime]
    confirmations: list[Confirmation] = Field(default_factory=list)

    @model_validator(mode="after")
    def consistent(self):
        if len(set(self.asset_ids)) != len(self.asset_ids) or any(not x.strip() for x in self.asset_ids):
            raise ValueError("素材ID必须非空且无重复")
        if set(self.requested_times) != set(self.asset_ids):
            raise ValueError("requested_times必须与素材集合完全一致")
        if any(c.asset_id not in self.asset_ids for c in self.confirmations):
            raise ValueError("确认引用了请求以外的素材")
        scopes = [(c.asset_id, c.kind, str(c.proposed_time), tuple(c.risk_codes)) for c in self.confirmations]
        if len(scopes) != len(set(scopes)):
            raise ValueError("同一确认范围不能重复或互相矛盾")
        return self


class CaseSpec(StrictModel):
    case_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
    request: RunRequest
    fixture: Literal["base", "slot_swap"] = "base"
    preset_answers: list[Confirmation] = Field(default_factory=list)


class AssetResult(StrictModel):
    asset_id: str
    review_status: Literal["approved", "blocked", "needs_info"]
    risk_reasons: list[str]
    requested_time: datetime
    suggested_time: datetime | None
    needs_confirmation: bool
    confirmation_reason: str | None
    _requested = field_validator("requested_time")(slot)

    @field_validator("suggested_time")
    @classmethod
    def suggested(cls, value):
        return slot(value) if value is not None else None


class PendingItem(StrictModel):
    asset_id: str | None = None
    kind: str = Field(min_length=1)
    message: str = Field(min_length=1)
    proposed_time: datetime | None = None
    risk_codes: list[str] = Field(default_factory=list)

    @field_validator("proposed_time")
    @classmethod
    def candidate_time(cls, value):
        return slot(value) if value is not None else None


class AgentResult(StrictModel):
    items: list[AssetResult]
    draft_status: Literal["saved", "duplicate", "failed", "not_saved"]
    draft_id: str | None
    status: Literal["completed", "needs_attention", "incomplete_step_limit", "incomplete_model_error"]
    pending_items: list[PendingItem]

    @model_validator(mode="after")
    def draft_reference(self):
        if (self.draft_status in ("saved", "duplicate")) != bool(self.draft_id):
            raise ValueError("草稿ID与保存状态不一致")
        return self


class ToolError(StrictModel):
    type: str
    message: str


class ToolObservation(StrictModel):
    ok: bool
    data: Any = None
    error: ToolError | None = None

    @model_validator(mode="after")
    def envelope(self):
        if self.ok == (self.error is not None) or (not self.ok and self.data is not None):
            raise ValueError("工具返回结构不一致")
        return self


class ToolArgs(StrictModel):
    reason: str = Field(default="", max_length=200)


class AssetArgs(ToolArgs):
    asset_id: str


class SlotArgs(ToolArgs):
    channel: str
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    around_time: datetime
    _around = field_validator("around_time")(slot)


class ConfirmArgs(AssetArgs):
    question: str = Field(min_length=1)
    confirmation_type: Literal["time_change", "risk_ack"] | None = None
    proposed_time: datetime | None = None
    risk_codes: list[str] = Field(default_factory=list)


class SaveArgs(ToolArgs):
    items: list[AssetResult] = Field(min_length=1)
    idempotency_key: str = Field(default="auto", description="传auto，由代码计算规范化请求与排期结果的SHA-256")


class FinishArgs(ToolArgs):
    result: AgentResult
