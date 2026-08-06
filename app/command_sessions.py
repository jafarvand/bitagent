from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from app.chat_commands import CommandState


TERMINAL_STATES = {"completed", "blocked"}


def _connect(path: str) -> sqlite3.Connection:
    database = Path(path)
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS command_sessions (
            session_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            state_json TEXT NOT NULL,
            state_hash TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_command_sessions_tenant_user
        ON command_sessions(tenant_id, user_id, updated_at DESC);

        CREATE TABLE IF NOT EXISTS command_session_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            event_type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            previous_hash TEXT NOT NULL,
            record_hash TEXT NOT NULL UNIQUE
        );
        """
    )
    return connection


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _audit(
    path: str,
    *,
    session_id: str,
    tenant_id: str,
    user_id: str,
    event_type: str,
    payload: dict,
) -> dict:
    created_at = datetime.now(UTC).isoformat()
    payload_json = _canonical(payload)
    with _connect(path) as connection:
        previous = connection.execute(
            "SELECT record_hash FROM command_session_events ORDER BY id DESC LIMIT 1"
        ).fetchone()
        previous_hash = previous["record_hash"] if previous else "0" * 64
        record_hash = hashlib.sha256(
            f"{previous_hash}\n{created_at}\n{session_id}\n{event_type}\n{payload_json}".encode()
        ).hexdigest()
        cursor = connection.execute(
            "INSERT INTO command_session_events "
            "(session_id,tenant_id,user_id,created_at,event_type,payload_json,previous_hash,record_hash) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (
                session_id,
                tenant_id,
                user_id,
                created_at,
                event_type,
                payload_json,
                previous_hash,
                record_hash,
            ),
        )
    return {"id": cursor.lastrowid, "created_at": created_at, "record_hash": record_hash}


def create_session(
    path: str,
    *,
    tenant_id: str,
    user_id: str,
    role: str,
    ttl_minutes: int = 30,
) -> dict:
    if ttl_minutes < 1 or ttl_minutes > 1440:
        raise ValueError("ttl_minutes must be between 1 and 1440")
    now = datetime.now(UTC)
    session_id = str(uuid4())
    state = CommandState(session_id=session_id)
    state_json = _canonical(state.model_dump())
    state_hash = hashlib.sha256(state_json.encode()).hexdigest()
    expires_at = now + timedelta(minutes=ttl_minutes)
    with _connect(path) as connection:
        connection.execute(
            "INSERT INTO command_sessions VALUES(?,?,?,?,?,?,?,?,?)",
            (
                session_id,
                tenant_id,
                user_id,
                role,
                now.isoformat(),
                now.isoformat(),
                expires_at.isoformat(),
                state_json,
                state_hash,
            ),
        )
    audit = _audit(
        path,
        session_id=session_id,
        tenant_id=tenant_id,
        user_id=user_id,
        event_type="session_created",
        payload={"role": role, "expires_at": expires_at.isoformat(), "state_hash": state_hash},
    )
    return {
        "session_id": session_id,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "role": role,
        "created_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
        "state": state.model_dump(),
        "state_hash": state_hash,
        "audit": audit,
    }


def load_session(
    path: str,
    *,
    session_id: str,
    tenant_id: str,
    user_id: str,
) -> dict | None:
    with _connect(path) as connection:
        row = connection.execute(
            "SELECT * FROM command_sessions WHERE session_id=? AND tenant_id=? AND user_id=?",
            (session_id, tenant_id, user_id),
        ).fetchone()
    if not row:
        return None
    expires_at = datetime.fromisoformat(row["expires_at"])
    expired = expires_at <= datetime.now(UTC)
    return {
        "session_id": row["session_id"],
        "tenant_id": row["tenant_id"],
        "user_id": row["user_id"],
        "role": row["role"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "expires_at": row["expires_at"],
        "expired": expired,
        "state": CommandState.model_validate_json(row["state_json"]),
        "state_hash": row["state_hash"],
    }


def save_state(
    path: str,
    *,
    tenant_id: str,
    user_id: str,
    state: CommandState,
    expected_state_hash: str,
) -> dict:
    loaded = load_session(
        path,
        session_id=state.session_id,
        tenant_id=tenant_id,
        user_id=user_id,
    )
    if not loaded:
        raise KeyError("session_not_found")
    if loaded["expired"]:
        raise ValueError("session_expired")
    if loaded["state_hash"] != expected_state_hash:
        raise ValueError("session_state_conflict")

    updated_at = datetime.now(UTC)
    state_json = _canonical(state.model_dump())
    state_hash = hashlib.sha256(state_json.encode()).hexdigest()
    with _connect(path) as connection:
        cursor = connection.execute(
            "UPDATE command_sessions SET updated_at=?,state_json=?,state_hash=? "
            "WHERE session_id=? AND tenant_id=? AND user_id=? AND state_hash=?",
            (
                updated_at.isoformat(),
                state_json,
                state_hash,
                state.session_id,
                tenant_id,
                user_id,
                expected_state_hash,
            ),
        )
        if cursor.rowcount != 1:
            raise ValueError("session_state_conflict")
    audit = _audit(
        path,
        session_id=state.session_id,
        tenant_id=tenant_id,
        user_id=user_id,
        event_type="state_updated",
        payload={"status": state.status, "intent": state.intent, "state_hash": state_hash},
    )
    return {
        "session_id": state.session_id,
        "updated_at": updated_at.isoformat(),
        "state": state.model_dump(),
        "state_hash": state_hash,
        "audit": audit,
    }


def cancel_session(
    path: str,
    *,
    session_id: str,
    tenant_id: str,
    user_id: str,
    expected_state_hash: str,
) -> dict:
    loaded = load_session(
        path,
        session_id=session_id,
        tenant_id=tenant_id,
        user_id=user_id,
    )
    if not loaded:
        raise KeyError("session_not_found")
    state: CommandState = loaded["state"]
    if state.status in TERMINAL_STATES:
        return {
            "session_id": session_id,
            "status": state.status,
            "replayed": True,
            "state_hash": loaded["state_hash"],
        }
    state.status = "blocked"
    state.missing_fields = []
    result = save_state(
        path,
        tenant_id=tenant_id,
        user_id=user_id,
        state=state,
        expected_state_hash=expected_state_hash,
    )
    result.update({"status": "cancelled", "replayed": False})
    return result
