"""Persistent trade-case state machine and audit log."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CASE_STATUSES = {"active", "paused", "completed", "cancelled", "failed"}
CASE_STAGES = (
    "draft",
    "advisor_review",
    "market_validation",
    "micro_backtest",
    "risk_review",
    "awaiting_confirmation",
    "execution",
    "review",
)
STAGE_INDEX = {stage: index for index, stage in enumerate(CASE_STAGES)}
ARTIFACT_STAGES = {
    "advisor": "advisor_review",
    "market": "market_validation",
    "chart": "market_validation",
    "micro_strategy": "micro_backtest",
    "risk": "risk_review",
    "pending_trade": "awaiting_confirmation",
    "execution": "execution",
    "trade_receipt": "review",
}
TERMINAL_STATUSES = {"completed", "cancelled"}


class TradeCaseConflict(RuntimeError):
    """Raised when a caller updates a stale case version."""


class TradeCaseTransitionError(ValueError):
    """Raised when a requested state transition is invalid."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_trade_case_db(db_path: Path) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trade_cases (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                title TEXT NOT NULL,
                objective TEXT NOT NULL,
                symbol TEXT NOT NULL,
                status TEXT NOT NULL,
                stage TEXT NOT NULL,
                version INTEGER NOT NULL,
                context_json TEXT NOT NULL,
                last_error TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trade_case_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                event_type TEXT NOT NULL,
                actor TEXT NOT NULL,
                stage TEXT NOT NULL,
                status TEXT NOT NULL,
                version INTEGER NOT NULL,
                message TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                FOREIGN KEY(case_id) REFERENCES trade_cases(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_trade_cases_updated ON trade_cases(updated_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_trade_case_events_case ON trade_case_events(case_id, id)"
        )
        columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(trade_cases)").fetchall()}
        if "broker_id" not in columns:
            conn.execute("ALTER TABLE trade_cases ADD COLUMN broker_id TEXT NOT NULL DEFAULT 'deriv'")


def _decode_case(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    result = dict(row)
    try:
        context = json.loads(str(result.pop("context_json") or "{}"))
    except json.JSONDecodeError:
        context = {}
    result["context"] = context if isinstance(context, dict) else {}
    return result


def _decode_event(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    try:
        payload = json.loads(str(result.pop("payload_json") or "{}"))
    except json.JSONDecodeError:
        payload = {}
    result["payload"] = payload if isinstance(payload, dict) else {}
    return result


def create_trade_case(
    db_path: Path,
    *,
    objective: str,
    symbol: str,
    broker_id: str = "deriv",
    title: str = "",
    case_id: str | None = None,
) -> dict[str, Any]:
    clean_objective = objective.strip()
    if not clean_objective:
        raise ValueError("objective is required")
    clean_symbol = symbol.strip() or "R_100"
    clean_broker_id = broker_id.strip().lower() or "deriv"
    created_at = _now()
    new_id = case_id or f"TC-{uuid.uuid4().hex[:12].upper()}"
    clean_title = title.strip() or clean_objective[:80]
    context = {"artifacts": {}, "notes": []}
    init_trade_case_db(db_path)
    with _connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            INSERT INTO trade_cases (
                id, created_at, updated_at, title, objective, symbol,
                status, stage, version, context_json, last_error, broker_id
            ) VALUES (?, ?, ?, ?, ?, ?, 'active', 'draft', 1, ?, NULL, ?)
            """,
            (
                new_id,
                created_at,
                created_at,
                clean_title,
                clean_objective,
                clean_symbol,
                json.dumps(context, ensure_ascii=False, default=str),
                clean_broker_id,
            ),
        )
        conn.execute(
            """
            INSERT INTO trade_case_events (
                case_id, created_at, event_type, actor, stage, status,
                version, message, payload_json
            ) VALUES (?, ?, 'created', 'operator', 'draft', 'active', 1, ?, ?)
            """,
            (
                new_id,
                created_at,
                "交易任务已创建",
                json.dumps({"objective": clean_objective, "symbol": clean_symbol, "broker_id": clean_broker_id}, ensure_ascii=False),
            ),
        )
    case = get_trade_case(db_path, new_id)
    if case is None:
        raise RuntimeError("trade case was not created")
    return case


def get_trade_case(db_path: Path, case_id: str) -> dict[str, Any] | None:
    init_trade_case_db(db_path)
    with _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM trade_cases WHERE id = ?", (case_id,)).fetchone()
    return _decode_case(row)


def list_trade_cases(db_path: Path, limit: int = 20) -> list[dict[str, Any]]:
    init_trade_case_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM trade_cases ORDER BY updated_at DESC LIMIT ?",
            (max(1, int(limit)),),
        ).fetchall()
    return [case for row in rows if (case := _decode_case(row)) is not None]


def list_trade_case_events(db_path: Path, case_id: str, limit: int = 200) -> list[dict[str, Any]]:
    init_trade_case_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM trade_case_events
            WHERE case_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (case_id, max(1, int(limit))),
        ).fetchall()
    return [_decode_event(row) for row in reversed(rows)]


def _next_stage(current: str, requested: str | None) -> str:
    if requested is None:
        return current
    if requested not in STAGE_INDEX:
        raise TradeCaseTransitionError(f"unknown stage: {requested}")
    if current not in STAGE_INDEX:
        return requested
    return requested if STAGE_INDEX[requested] >= STAGE_INDEX[current] else current


def update_trade_case(
    db_path: Path,
    case_id: str,
    *,
    actor: str,
    message: str,
    event_type: str,
    status: str | None = None,
    stage: str | None = None,
    artifact_type: str | None = None,
    payload: dict[str, Any] | None = None,
    expected_version: int | None = None,
    last_error: str | None = None,
) -> dict[str, Any]:
    init_trade_case_db(db_path)
    payload = payload or {}
    updated_at = _now()
    with _connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM trade_cases WHERE id = ?", (case_id,)).fetchone()
        current = _decode_case(row)
        if current is None:
            raise KeyError(f"unknown trade case: {case_id}")
        if expected_version is not None and int(current["version"]) != int(expected_version):
            raise TradeCaseConflict(
                f"stale trade case version: expected {expected_version}, current {current['version']}"
            )
        if current["status"] in TERMINAL_STATUSES:
            raise TradeCaseTransitionError(f"trade case is terminal: {current['status']}")

        next_status = status or str(current["status"])
        if next_status not in CASE_STATUSES:
            raise TradeCaseTransitionError(f"unknown status: {next_status}")
        next_stage = _next_stage(str(current["stage"]), stage)
        next_version = int(current["version"]) + 1
        context = dict(current.get("context") or {})
        artifacts = dict(context.get("artifacts") or {})
        if artifact_type:
            artifacts[artifact_type] = {
                "updated_at": updated_at,
                "actor": actor,
                "payload": payload,
                "version": next_version,
            }
            context["artifacts"] = artifacts

        result = conn.execute(
            """
            UPDATE trade_cases
            SET updated_at = ?, status = ?, stage = ?, version = ?,
                context_json = ?, last_error = ?
            WHERE id = ? AND version = ?
            """,
            (
                updated_at,
                next_status,
                next_stage,
                next_version,
                json.dumps(context, ensure_ascii=False, default=str),
                last_error,
                case_id,
                int(current["version"]),
            ),
        )
        if result.rowcount != 1:
            raise TradeCaseConflict("trade case changed during update")
        conn.execute(
            """
            INSERT INTO trade_case_events (
                case_id, created_at, event_type, actor, stage, status,
                version, message, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                case_id,
                updated_at,
                event_type,
                actor,
                next_stage,
                next_status,
                next_version,
                message,
                json.dumps(payload, ensure_ascii=False, default=str),
            ),
        )
    updated = get_trade_case(db_path, case_id)
    if updated is None:
        raise RuntimeError("trade case disappeared after update")
    return updated


def record_trade_case_artifact(
    db_path: Path,
    case_id: str,
    *,
    artifact_type: str,
    actor: str,
    message: str,
    payload: dict[str, Any],
    expected_version: int | None = None,
    advance_stage: bool = True,
    target_stage: str | None = None,
) -> dict[str, Any]:
    stage = target_stage if target_stage is not None else (ARTIFACT_STAGES.get(artifact_type) if advance_stage else None)
    status = "completed" if artifact_type == "trade_receipt" else None
    return update_trade_case(
        db_path,
        case_id,
        actor=actor,
        message=message,
        event_type="artifact",
        status=status,
        stage=stage,
        artifact_type=artifact_type,
        payload=payload,
        expected_version=expected_version,
    )


def control_trade_case(
    db_path: Path,
    case_id: str,
    action: str,
    *,
    actor: str = "operator",
    expected_version: int | None = None,
) -> dict[str, Any]:
    current = get_trade_case(db_path, case_id)
    if current is None:
        raise KeyError(f"unknown trade case: {case_id}")
    current_status = str(current["status"])
    allowed = {
        "pause": ({"active"}, "paused"),
        "resume": ({"paused"}, "active"),
        "cancel": ({"active", "paused", "failed"}, "cancelled"),
        "retry": ({"failed"}, "active"),
        "fail": ({"active", "paused"}, "failed"),
    }
    if action not in allowed:
        raise TradeCaseTransitionError(f"unknown control action: {action}")
    source_statuses, target_status = allowed[action]
    if current_status not in source_statuses:
        raise TradeCaseTransitionError(f"cannot {action} trade case from {current_status}")
    return update_trade_case(
        db_path,
        case_id,
        actor=actor,
        message=f"Trade case {action}",
        event_type="control",
        status=target_status,
        expected_version=expected_version,
        last_error=None if action in {"resume", "retry"} else current.get("last_error"),
    )
