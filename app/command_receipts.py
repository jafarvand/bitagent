from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field


class CommandReceipt(BaseModel):
    command_id: str = Field(min_length=3, max_length=100)
    session_id: str = Field(min_length=3, max_length=100)
    tenant_id: str = Field(min_length=1, max_length=100)
    user_id: str = Field(min_length=1, max_length=100)
    intent: str = Field(min_length=2, max_length=100)
    tool_name: str = Field(min_length=3, max_length=150)
    status: str = Field(pattern=r"^(succeeded|partial|blocked|failed|pending_verification|rolled_back)$")
    requested_at: str
    executed_at: str | None = None
    verified_at: str | None = None
    source_system_status: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    policy_decision: dict = Field(default_factory=dict)
    approval_ids: list[str] = Field(default_factory=list)
    idempotency_key: str | None = None
    rollback_available: bool = False
    action_executed: bool = False
    metadata: dict = Field(default_factory=dict)


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _connect(path: str) -> sqlite3.Connection:
    database = Path(path)
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS command_receipts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            command_id TEXT NOT NULL UNIQUE,
            session_id TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            receipt_json TEXT NOT NULL,
            previous_hash TEXT NOT NULL,
            record_hash TEXT NOT NULL UNIQUE
        );
        CREATE INDEX IF NOT EXISTS idx_command_receipts_tenant_session
        ON command_receipts(tenant_id,session_id,id DESC);
        """
    )
    return connection


def append_receipt(path: str, receipt: CommandReceipt) -> dict:
    created_at = datetime.now(UTC).isoformat()
    receipt_json = _canonical(receipt.model_dump())
    with _connect(path) as connection:
        existing = connection.execute(
            "SELECT id,record_hash FROM command_receipts WHERE command_id=?",
            (receipt.command_id,),
        ).fetchone()
        if existing:
            return {
                "command_id": receipt.command_id,
                "record_hash": existing["record_hash"],
                "replayed": True,
            }
        previous = connection.execute(
            "SELECT record_hash FROM command_receipts ORDER BY id DESC LIMIT 1"
        ).fetchone()
        previous_hash = previous["record_hash"] if previous else "0" * 64
        record_hash = hashlib.sha256(
            f"{previous_hash}\n{created_at}\n{receipt.command_id}\n{receipt_json}".encode()
        ).hexdigest()
        cursor = connection.execute(
            "INSERT INTO command_receipts "
            "(command_id,session_id,tenant_id,user_id,created_at,receipt_json,previous_hash,record_hash) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (
                receipt.command_id,
                receipt.session_id,
                receipt.tenant_id,
                receipt.user_id,
                created_at,
                receipt_json,
                previous_hash,
                record_hash,
            ),
        )
    return {
        "id": cursor.lastrowid,
        "command_id": receipt.command_id,
        "created_at": created_at,
        "previous_hash": previous_hash,
        "record_hash": record_hash,
        "replayed": False,
    }


def get_receipt(path: str, *, command_id: str, tenant_id: str) -> dict | None:
    with _connect(path) as connection:
        row = connection.execute(
            "SELECT * FROM command_receipts WHERE command_id=? AND tenant_id=?",
            (command_id, tenant_id),
        ).fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "receipt": json.loads(row["receipt_json"]),
        "previous_hash": row["previous_hash"],
        "record_hash": row["record_hash"],
    }


def list_session_receipts(
    path: str,
    *,
    tenant_id: str,
    session_id: str,
    limit: int = 50,
) -> list[dict]:
    if limit < 1 or limit > 200:
        raise ValueError("limit must be between 1 and 200")
    with _connect(path) as connection:
        rows = connection.execute(
            "SELECT * FROM command_receipts WHERE tenant_id=? AND session_id=? "
            "ORDER BY id DESC LIMIT ?",
            (tenant_id, session_id, limit),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "created_at": row["created_at"],
            "receipt": json.loads(row["receipt_json"]),
            "record_hash": row["record_hash"],
        }
        for row in rows
    ]


def verify_receipt_chain(path: str) -> dict:
    with _connect(path) as connection:
        rows = connection.execute(
            "SELECT * FROM command_receipts ORDER BY id ASC"
        ).fetchall()
    expected_previous = "0" * 64
    failures = []
    for row in rows:
        expected_hash = hashlib.sha256(
            f"{expected_previous}\n{row['created_at']}\n{row['command_id']}\n{row['receipt_json']}".encode()
        ).hexdigest()
        if row["previous_hash"] != expected_previous:
            failures.append({"id": row["id"], "reason": "previous_hash_mismatch"})
        if row["record_hash"] != expected_hash:
            failures.append({"id": row["id"], "reason": "record_hash_mismatch"})
        expected_previous = row["record_hash"]
    return {
        "valid": not failures,
        "records": len(rows),
        "head_hash": expected_previous,
        "failures": failures,
    }


def verified_status(
    *,
    requested_status: str,
    source_verified: bool,
    source_system_status: str | None,
) -> str:
    if requested_status in {"blocked", "failed", "rolled_back"}:
        return requested_status
    if not source_verified or not source_system_status:
        return "pending_verification"
    return requested_status
