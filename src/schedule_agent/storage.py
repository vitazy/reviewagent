from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .schemas import utc


class BusinessError(Exception):
    def __init__(self, kind: str, message: str):
        self.kind = kind
        super().__init__(message)


@contextmanager
def connection(path: Path):
    db = sqlite3.connect(path, timeout=3)
    db.row_factory = sqlite3.Row
    try:
        yield db
    finally:
        db.close()


def seed_db(path: Path, fixture: str = "base", reset: bool = False):
    if path.exists() and not reset:
        raise ValueError("数据库已存在；仅在明确需要清空时使用 --reset")
    path.parent.mkdir(parents=True, exist_ok=True)
    with connection(path) as db:
        db.executescript("""
        DROP TABLE IF EXISTS assets;
        DROP TABLE IF EXISTS schedule;
        DROP TABLE IF EXISTS drafts;
        CREATE TABLE assets (
          asset_id TEXT PRIMARY KEY, title TEXT, copyright_status TEXT, content TEXT,
          music_authorized INTEGER, manual_review_required INTEGER, revision INTEGER);
        CREATE TABLE schedule (
          id INTEGER PRIMARY KEY, channel TEXT NOT NULL, start_time_utc TEXT NOT NULL,
          asset_id TEXT NOT NULL, UNIQUE(channel, start_time_utc));
        CREATE TABLE drafts (
          draft_id TEXT PRIMARY KEY, idempotency_key TEXT NOT NULL UNIQUE,
          request_json TEXT NOT NULL, items_json TEXT NOT NULL, created_at TEXT NOT NULL);
        """)
        db.executemany("INSERT INTO assets VALUES (?, ?, ?, ?, ?, ?, ?)", [
            ("M01", "秋日旅行", "licensed", "原创旅行记录", 1, 0, 1),
            ("M02", None, None, "素材资料待补充", 1, 0, 1),
            ("M03", "风险素材", "licensed", "违规推广", 0, 0, 1),
            ("M04", "边界题材", "licensed", "需人工评估的边界题材", 1, 1, 1),
        ])
        hours = [18, 19] if fixture == "slot_swap" else [18]
        db.executemany("INSERT INTO schedule(channel,start_time_utc,asset_id) VALUES(?,?,?)", [
            ("video", utc(f"2026-10-30T{hour}:00:00+08:00"), f"EXISTING_{hour}") for hour in hours
        ])
        db.commit()


def get_asset(path: Path, asset_id: str) -> dict:
    with connection(path) as db:
        row = db.execute("SELECT * FROM assets WHERE asset_id=?", (asset_id,)).fetchone()
    if row is None:
        raise BusinessError("AssetNotFound", "素材不存在")
    return dict(row)


def occupied(path: Path, channel: str) -> set[str]:
    with connection(path) as db:
        return {r[0] for r in db.execute("SELECT start_time_utc FROM schedule WHERE channel=?", (channel,))}


def persist(path: Path, key: str, request_json: dict, canonical_items: list[dict]) -> dict:
    """Serialize duplicate check, live slot check, and insert within one transaction."""
    with connection(path) as db:
        try:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT * FROM drafts WHERE idempotency_key=?", (key,)).fetchone()
            if existing:
                db.rollback()
                return {"draft_status": "duplicate", "draft_id": existing["draft_id"],
                        "idempotency_key": key, "items": json.loads(existing["items_json"])}
            for item in canonical_items:
                conflict = db.execute("SELECT 1 FROM schedule WHERE channel=? AND start_time_utc=?",
                                      (item["channel"], item["suggested_time"])).fetchone()
                if conflict:
                    raise BusinessError("SlotUnavailable", "保存时发现时段已被占用，请重新查询")
            draft_id = "D-" + uuid.uuid4().hex[:16]
            db.execute("INSERT INTO drafts VALUES(?,?,?,?,?)", (
                draft_id, key, json.dumps(request_json, ensure_ascii=False),
                json.dumps(canonical_items, ensure_ascii=False), datetime.now(timezone.utc).isoformat()))
            try:
                db.commit()
            except sqlite3.Error:
                # Never turn an uncertain commit into an invented success.
                db.rollback()
                with connection(path) as check:
                    found = check.execute("SELECT draft_id FROM drafts WHERE idempotency_key=?", (key,)).fetchone()
                if not found:
                    raise
                draft_id = found[0]
            return {"draft_status": "saved", "draft_id": draft_id, "idempotency_key": key, "items": canonical_items}
        except Exception:
            db.rollback()
            raise


def verify_saved(path: Path, saved: dict) -> bool:
    with connection(path) as db:
        row = db.execute("SELECT * FROM drafts WHERE draft_id=? AND idempotency_key=?",
                         (saved["draft_id"], saved["idempotency_key"])).fetchone()
    return bool(row and json.loads(row["items_json"]) == saved["items"])
