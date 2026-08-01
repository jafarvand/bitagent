import hashlib
import hmac
import json
import secrets
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


SandboxAction = Literal["route_test_case", "create_draft_task", "send_test_notification"]


class ActionPreviewRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=100)
    action_type: SandboxAction
    target_id: str = Field(min_length=2, max_length=100)
    parameters: dict = Field(min_length=1)
    expected_effect: str = Field(min_length=3, max_length=500)
    risk: Literal["low"]
    environment: Literal["development", "test", "staging"]
    evidence_refs: list[str] = Field(min_length=1, max_length=100)
    rollback_plan: str = Field(min_length=3, max_length=1000)
    timeout_seconds: int = Field(ge=1, le=60)
    requester: str = Field(min_length=2, max_length=100)


class ActionAuthorizationRequest(BaseModel):
    preview_id: str = Field(min_length=3, max_length=100)
    maker: str = Field(min_length=2, max_length=100)
    checker: str = Field(min_length=2, max_length=100)
    expires_at: datetime

    @model_validator(mode="after")
    def validate_approval(self):
        now = datetime.now(UTC)
        if self.maker == self.checker:
            raise ValueError("maker and checker must be different")
        if self.expires_at <= now or self.expires_at > now + timedelta(minutes=15):
            raise ValueError("authorization expiry must be within the next 15 minutes")
        return self


class ActionExecutionRequest(BaseModel):
    authorization_id: str = Field(min_length=3, max_length=100)
    authorization_token: str = Field(min_length=20, max_length=500)
    preview_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    idempotency_key: str = Field(min_length=8, max_length=100)
    simulation_outcome: Literal["success", "partial_failure", "timeout"] = "success"


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _connect(path: str) -> sqlite3.Connection:
    database = Path(path)
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS xima_action_control (
            singleton INTEGER PRIMARY KEY CHECK(singleton=1), paused INTEGER NOT NULL,
            signing_secret TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS xima_action_previews (
            preview_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, tenant_id TEXT NOT NULL,
            action_type TEXT NOT NULL, requester TEXT NOT NULL, preview_json TEXT NOT NULL,
            preview_hash TEXT NOT NULL UNIQUE
        );
        CREATE TABLE IF NOT EXISTS xima_action_authorizations (
            authorization_id TEXT PRIMARY KEY, preview_id TEXT NOT NULL,
            created_at TEXT NOT NULL, expires_at TEXT NOT NULL, maker TEXT NOT NULL,
            checker TEXT NOT NULL, preview_hash TEXT NOT NULL, token_hash TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS xima_action_executions (
            execution_id TEXT PRIMARY KEY, authorization_id TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL,
            status TEXT NOT NULL, preview_hash TEXT NOT NULL, verification_passed INTEGER NOT NULL,
            rolled_back INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS xima_action_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
            event_type TEXT NOT NULL, entity_id TEXT NOT NULL, payload_json TEXT NOT NULL,
            previous_hash TEXT NOT NULL, record_hash TEXT NOT NULL UNIQUE
        );
        """
    )
    existing = connection.execute(
        "SELECT singleton FROM xima_action_control WHERE singleton=1"
    ).fetchone()
    if not existing:
        connection.execute(
            "INSERT INTO xima_action_control(singleton,paused,signing_secret) VALUES(1,0,?)",
            (secrets.token_hex(32),),
        )
        connection.commit()
    return connection


def _audit(path: str, event_type: str, entity_id: str, payload: dict) -> dict:
    created_at = datetime.now(UTC).isoformat()
    payload_json = _canonical(payload)
    with _connect(path) as connection:
        previous = connection.execute(
            "SELECT record_hash FROM xima_action_audit ORDER BY id DESC LIMIT 1"
        ).fetchone()
        previous_hash = previous["record_hash"] if previous else "0" * 64
        record_hash = hashlib.sha256(
            f"{previous_hash}\n{created_at}\n{event_type}\n{entity_id}\n{payload_json}".encode()
        ).hexdigest()
        cursor = connection.execute(
            "INSERT INTO xima_action_audit "
            "(created_at,event_type,entity_id,payload_json,previous_hash,record_hash) VALUES(?,?,?,?,?,?)",
            (created_at, event_type, entity_id, payload_json, previous_hash, record_hash),
        )
    return {"id": cursor.lastrowid, "created_at": created_at, "record_hash": record_hash}


def create_preview(path: str, request: ActionPreviewRequest) -> dict:
    preview_id = str(uuid4())
    created_at = datetime.now(UTC).isoformat()
    preview = {
        **request.model_dump(), "preview_id": preview_id, "created_at": created_at,
        "prerequisites": ["exact maker-checker authorization", "kill switch clear",
                          "unexpired token", "idempotency key"],
        "executor": "local_sandbox_only", "exchange_request_enabled": False,
    }
    preview_json = _canonical(preview)
    preview_hash = hashlib.sha256(preview_json.encode()).hexdigest()
    with _connect(path) as connection:
        connection.execute(
            "INSERT INTO xima_action_previews VALUES(?,?,?,?,?,?,?)",
            (preview_id, created_at, request.tenant_id, request.action_type,
             request.requester, preview_json, preview_hash),
        )
    result = {**preview, "preview_hash": preview_hash, "approval_required": True}
    result["audit"] = _audit(path, "action_previewed", preview_id, result)
    return result


def authorize_preview(path: str, request: ActionAuthorizationRequest) -> tuple[int, dict]:
    with _connect(path) as connection:
        preview = connection.execute(
            "SELECT * FROM xima_action_previews WHERE preview_id=?", (request.preview_id,),
        ).fetchone()
        if not preview:
            return 404, {"code": "preview_not_found"}
        authorization_id = str(uuid4())
        created_at = datetime.now(UTC).isoformat()
        material = f"{authorization_id}:{preview['preview_hash']}:{request.expires_at.isoformat()}"
        secret = connection.execute(
            "SELECT signing_secret FROM xima_action_control WHERE singleton=1"
        ).fetchone()["signing_secret"]
        signature = hmac.new(secret.encode(), material.encode(), hashlib.sha256).hexdigest()
        token = f"{authorization_id}.{signature}"
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        connection.execute(
            "INSERT INTO xima_action_authorizations VALUES(?,?,?,?,?,?,?,?)",
            (authorization_id, request.preview_id, created_at, request.expires_at.isoformat(),
             request.maker, request.checker, preview["preview_hash"], token_hash),
        )
    result = {
        "authorization_id": authorization_id, "preview_id": request.preview_id,
        "preview_hash": preview["preview_hash"], "created_at": created_at,
        "expires_at": request.expires_at.isoformat(), "maker": request.maker,
        "checker": request.checker, "authorization_token": token,
        "scope": "local_low_risk_sandbox_only",
    }
    result["audit"] = _audit(path, "action_authorized", authorization_id,
                              {key: value for key, value in result.items()
                               if key != "authorization_token"})
    return 201, result


def execute_action(path: str, request: ActionExecutionRequest) -> tuple[int, dict]:
    with _connect(path) as connection:
        existing = connection.execute(
            "SELECT * FROM xima_action_executions WHERE idempotency_key=?",
            (request.idempotency_key,),
        ).fetchone()
        if existing:
            return 200, {"execution_id": existing["execution_id"],
                         "status": existing["status"], "replayed": True}
        control = connection.execute(
            "SELECT paused FROM xima_action_control WHERE singleton=1"
        ).fetchone()
        if control["paused"]:
            return 409, {"code": "action_kill_switch_active"}
        already_used = connection.execute(
            "SELECT execution_id FROM xima_action_executions WHERE authorization_id=?",
            (request.authorization_id,),
        ).fetchone()
        if already_used:
            return 409, {"code": "authorization_already_used",
                         "execution_id": already_used["execution_id"]}
        authorization = connection.execute(
            "SELECT * FROM xima_action_authorizations WHERE authorization_id=?",
            (request.authorization_id,),
        ).fetchone()
        if not authorization:
            return 404, {"code": "authorization_not_found"}
        if datetime.fromisoformat(authorization["expires_at"]) <= datetime.now(UTC):
            return 409, {"code": "authorization_expired"}
        if not hmac.compare_digest(
            authorization["token_hash"], hashlib.sha256(request.authorization_token.encode()).hexdigest()
        ):
            return 403, {"code": "authorization_signature_invalid"}
        if not hmac.compare_digest(authorization["preview_hash"], request.preview_hash):
            return 409, {"code": "preview_hash_mismatch"}
        execution_id = str(uuid4())
        status = {"success": "succeeded", "partial_failure": "partial_failure",
                  "timeout": "timed_out"}[request.simulation_outcome]
        verification_passed = status == "succeeded"
        connection.execute(
            "INSERT INTO xima_action_executions "
            "(execution_id,authorization_id,idempotency_key,created_at,status,preview_hash,"
            "verification_passed,rolled_back) VALUES(?,?,?,?,?,?,?,0)",
            (execution_id, request.authorization_id, request.idempotency_key,
             datetime.now(UTC).isoformat(), status, request.preview_hash, verification_passed),
        )
    result = {
        "execution_id": execution_id, "status": status, "replayed": False,
        "verification": {"passed": verification_passed,
                         "result": "expected_effect_confirmed" if verification_passed else
                                   "manual_review_and_rollback_required"},
        "rollback_available": status in {"succeeded", "partial_failure"},
        "executor": "local_sandbox_only", "exchange_request_sent": False,
    }
    result["audit"] = _audit(path, "action_execution_result", execution_id, result)
    return 201, result


def rollback_action(path: str, execution_id: str) -> tuple[int, dict]:
    with _connect(path) as connection:
        row = connection.execute(
            "SELECT * FROM xima_action_executions WHERE execution_id=?", (execution_id,),
        ).fetchone()
        if not row:
            return 404, {"code": "execution_not_found"}
        if row["status"] == "timed_out":
            return 409, {"code": "rollback_not_available"}
        if row["rolled_back"]:
            return 200, {"execution_id": execution_id, "status": "rolled_back", "replayed": True}
        connection.execute(
            "UPDATE xima_action_executions SET status='rolled_back',rolled_back=1 WHERE execution_id=?",
            (execution_id,),
        )
    result = {"execution_id": execution_id, "status": "rolled_back", "replayed": False,
              "exchange_request_sent": False}
    result["audit"] = _audit(path, "action_rolled_back", execution_id, result)
    return 200, result


def set_kill_switch(path: str, paused: bool) -> dict:
    with _connect(path) as connection:
        connection.execute(
            "UPDATE xima_action_control SET paused=? WHERE singleton=1", (paused,),
        )
    result = {"paused": paused, "scope": "all_xima_sandbox_actions"}
    result["audit"] = _audit(path, "action_kill_switch_changed", "global", result)
    return result
