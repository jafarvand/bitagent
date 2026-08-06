from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


class ApprovalRequestCreate(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=100)
    tool_name: str = Field(min_length=3, max_length=150)
    requester_id: str = Field(min_length=1, max_length=100)
    requester_role: str = Field(min_length=1, max_length=100)
    arguments: dict = Field(min_length=1)
    risk: str = Field(pattern=r"^(low|medium|high)$")
    approval_policy: str = Field(pattern=r"^(single_approval|maker_checker)$")
    reason: str = Field(min_length=3, max_length=1000)
    plan_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    expires_in_minutes: int = Field(default=15, ge=1, le=1440)


class ApprovalDecision(BaseModel):
    approver_id: str = Field(min_length=1, max_length=100)
    approver_role: str = Field(min_length=1, max_length=100)
    decision: str = Field(pattern=r"^(approve|reject)$")
    reason: str = Field(min_length=3, max_length=1000)
    expected_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=100)


class ApprovalCancellation(BaseModel):
    actor_id: str = Field(min_length=1, max_length=100)
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=1000)


class ApprovalRecord(BaseModel):
    request_id: str
    tenant_id: str
    tool_name: str
    requester_id: str
    requester_role: str
    arguments: dict
    risk: str
    approval_policy: str
    reason: str
    plan_hash: str
    status: str
    version: int
    created_at: str
    updated_at: str
    expires_at: str
    approver_id: str | None = None
    approver_role: str | None = None
    decision_reason: str | None = None

    @model_validator(mode="after")
    def validate_status(self):
        if self.status not in {"pending", "approved", "rejected", "cancelled", "expired"}:
            raise ValueError("invalid approval status")
        return self


def _connect(path: str) -> sqlite3.Connection:
    database = Path(path)
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS command_approvals (
            request_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            tool_name TEXT NOT NULL,
            requester_id TEXT NOT NULL,
            requester_role TEXT NOT NULL,
            arguments_json TEXT NOT NULL,
            risk TEXT NOT NULL,
            approval_policy TEXT NOT NULL,
            reason TEXT NOT NULL,
            plan_hash TEXT NOT NULL,
            status TEXT NOT NULL,
            version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            approver_id TEXT,
            approver_role TEXT,
            decision_reason TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_command_approvals_pending
        ON command_approvals(tenant_id,status,expires_at);

        CREATE TABLE IF NOT EXISTS command_approval_decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            action TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            record_hash TEXT NOT NULL UNIQUE
        );
        """
    )
    return connection


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _row_to_record(row: sqlite3.Row) -> ApprovalRecord:
    now = datetime.now(UTC)
    status = row["status"]
    if status == "pending" and datetime.fromisoformat(row["expires_at"]) <= now:
        status = "expired"
    return ApprovalRecord(
        request_id=row["request_id"],
        tenant_id=row["tenant_id"],
        tool_name=row["tool_name"],
        requester_id=row["requester_id"],
        requester_role=row["requester_role"],
        arguments=json.loads(row["arguments_json"]),
        risk=row["risk"],
        approval_policy=row["approval_policy"],
        reason=row["reason"],
        plan_hash=row["plan_hash"],
        status=status,
        version=row["version"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        expires_at=row["expires_at"],
        approver_id=row["approver_id"],
        approver_role=row["approver_role"],
        decision_reason=row["decision_reason"],
    )


def create_approval(path: str, request: ApprovalRequestCreate) -> dict:
    now = datetime.now(UTC)
    request_id = f"APR-{uuid4().hex[:12].upper()}"
    expires_at = now + timedelta(minutes=request.expires_in_minutes)
    arguments_json = _canonical(request.arguments)
    with _connect(path) as connection:
        connection.execute(
            "INSERT INTO command_approvals VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                request_id,
                request.tenant_id,
                request.tool_name,
                request.requester_id,
                request.requester_role,
                arguments_json,
                request.risk,
                request.approval_policy,
                request.reason,
                request.plan_hash,
                "pending",
                1,
                now.isoformat(),
                now.isoformat(),
                expires_at.isoformat(),
                None,
                None,
                None,
            ),
        )
    return {
        "request_id": request_id,
        "status": "pending",
        "version": 1,
        "expires_at": expires_at.isoformat(),
        "approval_policy": request.approval_policy,
        "action_executed": False,
    }


def get_approval(path: str, *, request_id: str, tenant_id: str) -> ApprovalRecord | None:
    with _connect(path) as connection:
        row = connection.execute(
            "SELECT * FROM command_approvals WHERE request_id=? AND tenant_id=?",
            (request_id, tenant_id),
        ).fetchone()
        if not row:
            return None
        record = _row_to_record(row)
        if record.status == "expired" and row["status"] == "pending":
            connection.execute(
                "UPDATE command_approvals SET status='expired',version=version+1,updated_at=? "
                "WHERE request_id=? AND status='pending'",
                (datetime.now(UTC).isoformat(), request_id),
            )
            row = connection.execute(
                "SELECT * FROM command_approvals WHERE request_id=?", (request_id,)
            ).fetchone()
            record = _row_to_record(row)
    return record


def list_pending(path: str, *, tenant_id: str) -> list[dict]:
    with _connect(path) as connection:
        rows = connection.execute(
            "SELECT * FROM command_approvals WHERE tenant_id=? AND status='pending' "
            "ORDER BY created_at ASC",
            (tenant_id,),
        ).fetchall()
    results = []
    for row in rows:
        record = _row_to_record(row)
        if record.status == "pending":
            results.append(record.model_dump())
    return results


def decide_approval(path: str, *, request_id: str, tenant_id: str, decision: ApprovalDecision) -> dict:
    with _connect(path) as connection:
        existing = connection.execute(
            "SELECT payload_json FROM command_approval_decisions WHERE idempotency_key=?",
            (decision.idempotency_key,),
        ).fetchone()
        if existing:
            payload = json.loads(existing["payload_json"])
            payload["replayed"] = True
            return payload

        row = connection.execute(
            "SELECT * FROM command_approvals WHERE request_id=? AND tenant_id=?",
            (request_id, tenant_id),
        ).fetchone()
        if not row:
            return {"code": "approval_not_found", "status": 404}
        record = _row_to_record(row)
        if record.status != "pending":
            return {"code": f"approval_{record.status}", "status": 409}
        if record.version != decision.expected_version:
            return {"code": "approval_version_conflict", "status": 409}
        if record.approval_policy == "maker_checker" and record.requester_id == decision.approver_id:
            return {"code": "maker_checker_separation_required", "status": 403}
        if decision.approver_role not in {"approver", "manager", "admin", "risk", "compliance"}:
            return {"code": "approver_role_not_authorized", "status": 403}

        new_status = "approved" if decision.decision == "approve" else "rejected"
        now = datetime.now(UTC).isoformat()
        new_version = record.version + 1
        cursor = connection.execute(
            "UPDATE command_approvals SET status=?,version=?,updated_at=?,approver_id=?,"
            "approver_role=?,decision_reason=? WHERE request_id=? AND version=? AND status='pending'",
            (
                new_status,
                new_version,
                now,
                decision.approver_id,
                decision.approver_role,
                decision.reason,
                request_id,
                decision.expected_version,
            ),
        )
        if cursor.rowcount != 1:
            return {"code": "approval_version_conflict", "status": 409}
        payload = {
            "request_id": request_id,
            "status": new_status,
            "version": new_version,
            "approver_id": decision.approver_id,
            "approver_role": decision.approver_role,
            "decision_reason": decision.reason,
            "plan_hash": record.plan_hash,
            "replayed": False,
            "action_executed": False,
        }
        record_hash = hashlib.sha256(_canonical(payload).encode()).hexdigest()
        connection.execute(
            "INSERT INTO command_approval_decisions "
            "(request_id,idempotency_key,created_at,actor_id,action,payload_json,record_hash) "
            "VALUES(?,?,?,?,?,?,?)",
            (
                request_id,
                decision.idempotency_key,
                now,
                decision.approver_id,
                decision.decision,
                _canonical(payload),
                record_hash,
            ),
        )
    payload["record_hash"] = record_hash
    return payload


def cancel_approval(
    path: str,
    *,
    request_id: str,
    tenant_id: str,
    cancellation: ApprovalCancellation,
) -> dict:
    with _connect(path) as connection:
        row = connection.execute(
            "SELECT * FROM command_approvals WHERE request_id=? AND tenant_id=?",
            (request_id, tenant_id),
        ).fetchone()
        if not row:
            return {"code": "approval_not_found", "status": 404}
        record = _row_to_record(row)
        if record.status != "pending":
            return {"code": f"approval_{record.status}", "status": 409}
        if record.requester_id != cancellation.actor_id:
            return {"code": "only_requester_can_cancel", "status": 403}
        if record.version != cancellation.expected_version:
            return {"code": "approval_version_conflict", "status": 409}
        new_version = record.version + 1
        connection.execute(
            "UPDATE command_approvals SET status='cancelled',version=?,updated_at=?,decision_reason=? "
            "WHERE request_id=? AND version=? AND status='pending'",
            (
                new_version,
                datetime.now(UTC).isoformat(),
                cancellation.reason,
                request_id,
                cancellation.expected_version,
            ),
        )
    return {
        "request_id": request_id,
        "status": "cancelled",
        "version": new_version,
        "action_executed": False,
    }
