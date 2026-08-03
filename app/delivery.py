import hashlib
import hmac
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import AwareDatetime, BaseModel, Field


Severity = Literal["info", "low", "medium", "high", "critical"]
_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


class EventIngressRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=100)
    event_id: str = Field(min_length=3, max_length=150)
    source_id: str = Field(min_length=2, max_length=100)
    domain: Literal["operations", "market_risk", "treasury", "aml_fraud", "security", "support", "governance"]
    event_type: str = Field(min_length=2, max_length=100)
    severity: Severity
    occurred_at: AwareDatetime
    evidence_refs: list[str] = Field(min_length=1, max_length=100)
    payload: dict = Field(default_factory=dict)


class NotificationSubscriptionRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=100)
    domain: str = Field(min_length=2, max_length=100)
    event_type: str = Field(min_length=1, max_length=100)
    minimum_severity: Severity
    channel: Literal["email", "chat", "on_call"]
    destination_ref: str = Field(min_length=3, max_length=200)
    owner: str = Field(min_length=2, max_length=100)


class ReportScheduleRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=100)
    report_type: Literal["executive", "operations", "market_risk", "treasury", "aml_fraud", "security", "support"]
    interval_minutes: int = Field(ge=15, le=10080)
    next_run_at: AwareDatetime
    recipient_refs: list[str] = Field(min_length=1, max_length=100)
    owner: str = Field(min_length=2, max_length=100)


def verify_webhook_signature(
    body: bytes, signature: str, secret: str, timestamp: str
) -> bool:
    if not secret or len(signature) != 64 or not timestamp:
        return False
    expected = hmac.new(
        secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def webhook_timestamp_is_fresh(
    timestamp: str, tolerance_seconds: int, now: datetime | None = None
) -> bool:
    try:
        received = datetime.fromtimestamp(int(timestamp), tz=UTC)
    except (ValueError, TypeError, OverflowError):
        return False
    current = now or datetime.now(UTC)
    return abs((current - received).total_seconds()) <= tolerance_seconds


def _connect(path: str) -> sqlite3.Connection:
    database = Path(path); database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database); connection.row_factory = sqlite3.Row
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS delivery_subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, subscription_id TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL, tenant_id TEXT NOT NULL, domain TEXT NOT NULL,
            event_type TEXT NOT NULL, minimum_severity TEXT NOT NULL, channel TEXT NOT NULL,
            destination_ref TEXT NOT NULL, owner TEXT NOT NULL, active INTEGER NOT NULL,
            record_hash TEXT NOT NULL UNIQUE);
        CREATE TABLE IF NOT EXISTS delivery_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, receipt_id TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL, tenant_id TEXT NOT NULL, event_id TEXT NOT NULL,
            source_id TEXT NOT NULL, domain TEXT NOT NULL, event_type TEXT NOT NULL,
            severity TEXT NOT NULL, occurred_at TEXT NOT NULL, payload_hash TEXT NOT NULL,
            record_hash TEXT NOT NULL UNIQUE, UNIQUE(tenant_id,event_id));
        CREATE TABLE IF NOT EXISTS delivery_outbox (
            id INTEGER PRIMARY KEY AUTOINCREMENT, notification_id TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL, tenant_id TEXT NOT NULL, event_id TEXT NOT NULL,
            subscription_id TEXT NOT NULL, channel TEXT NOT NULL, destination_ref TEXT NOT NULL,
            severity TEXT NOT NULL, status TEXT NOT NULL, deduplication_key TEXT NOT NULL UNIQUE,
            acknowledged_at TEXT, acknowledged_by TEXT, record_hash TEXT NOT NULL UNIQUE);
        CREATE TABLE IF NOT EXISTS delivery_report_schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT, schedule_id TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL, tenant_id TEXT NOT NULL, report_type TEXT NOT NULL,
            interval_minutes INTEGER NOT NULL, next_run_at TEXT NOT NULL,
            recipient_refs_json TEXT NOT NULL, owner TEXT NOT NULL, active INTEGER NOT NULL,
            record_hash TEXT NOT NULL UNIQUE);
        CREATE TABLE IF NOT EXISTS delivery_report_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL, tenant_id TEXT NOT NULL, schedule_id TEXT NOT NULL,
            report_type TEXT NOT NULL, recipient_refs_json TEXT NOT NULL, status TEXT NOT NULL,
            payload_hash TEXT NOT NULL, record_hash TEXT NOT NULL UNIQUE);
    """)
    return connection


def create_subscription(path: str, request: NotificationSubscriptionRequest) -> dict:
    subscription_id, created_at = str(uuid4()), datetime.now(UTC).isoformat()
    material = json.dumps(request.model_dump(), sort_keys=True, separators=(",", ":"))
    record_hash = hashlib.sha256(f"{subscription_id}\n{created_at}\n{material}".encode()).hexdigest()
    with _connect(path) as connection:
        cursor = connection.execute(
            "INSERT INTO delivery_subscriptions (subscription_id,created_at,tenant_id,domain,event_type,minimum_severity,channel,destination_ref,owner,active,record_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (subscription_id, created_at, request.tenant_id, request.domain, request.event_type,
             request.minimum_severity, request.channel, request.destination_ref, request.owner, 1, record_hash))
    return {"id": cursor.lastrowid, "subscription_id": subscription_id,
            "created_at": created_at, "record_hash": record_hash, "active": True,
            "external_message_sent": False}


def subscriptions(path: str, tenant_id: str, limit: int = 100) -> list[dict]:
    with _connect(path) as connection:
        rows = connection.execute(
            "SELECT subscription_id,created_at,tenant_id,domain,event_type,minimum_severity,channel,destination_ref,owner,active,record_hash FROM delivery_subscriptions WHERE tenant_id=? ORDER BY id DESC LIMIT ?",
            (tenant_id, limit),
        ).fetchall()
    return [{**dict(row), "active": bool(row["active"])} for row in rows]


def ingest_event(path: str, request: EventIngressRequest) -> tuple[int, dict]:
    receipt_id, created_at = str(uuid4()), datetime.now(UTC).isoformat()
    payload_json = json.dumps(request.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    payload_hash = hashlib.sha256(payload_json.encode()).hexdigest()
    record_hash = hashlib.sha256(f"{receipt_id}\n{created_at}\n{payload_hash}".encode()).hexdigest()
    with _connect(path) as connection:
        try:
            cursor = connection.execute(
                "INSERT INTO delivery_events (receipt_id,created_at,tenant_id,event_id,source_id,domain,event_type,severity,occurred_at,payload_hash,record_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (receipt_id, created_at, request.tenant_id, request.event_id, request.source_id,
                 request.domain, request.event_type, request.severity, request.occurred_at.isoformat(),
                 payload_hash, record_hash))
        except sqlite3.IntegrityError:
            return 409, {"code": "event_duplicate", "tenant_id": request.tenant_id,
                         "event_id": request.event_id}
        subscriptions = connection.execute(
            "SELECT * FROM delivery_subscriptions WHERE tenant_id=? AND active=1 AND (domain=? OR domain='*') AND (event_type=? OR event_type='*')",
            (request.tenant_id, request.domain, request.event_type)).fetchall()
        notifications = []
        for subscription in subscriptions:
            if _RANK[request.severity] < _RANK[subscription["minimum_severity"]]:
                continue
            notification_id = str(uuid4())
            dedupe = hashlib.sha256(
                f"{request.tenant_id}:{request.event_id}:{subscription['subscription_id']}".encode()).hexdigest()
            notification_hash = hashlib.sha256(
                f"{notification_id}\n{created_at}\n{dedupe}".encode()).hexdigest()
            connection.execute(
                "INSERT INTO delivery_outbox (notification_id,created_at,tenant_id,event_id,subscription_id,channel,destination_ref,severity,status,deduplication_key,record_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (notification_id, created_at, request.tenant_id, request.event_id,
                 subscription["subscription_id"], subscription["channel"],
                 subscription["destination_ref"], request.severity, "queued", dedupe,
                 notification_hash))
            notifications.append({"notification_id": notification_id,
                                  "channel": subscription["channel"], "status": "queued",
                                  "deduplication_key": dedupe})
    return 201, {"id": cursor.lastrowid, "receipt_id": receipt_id,
                 "tenant_id": request.tenant_id, "event_id": request.event_id,
                 "payload_hash": payload_hash, "record_hash": record_hash,
                 "notifications": notifications, "external_message_sent": False}


def outbox(path: str, tenant_id: str, limit: int = 100) -> list[dict]:
    with _connect(path) as connection:
        rows = connection.execute(
            "SELECT notification_id,created_at,tenant_id,event_id,subscription_id,channel,destination_ref,severity,status,deduplication_key,acknowledged_at,acknowledged_by,record_hash FROM delivery_outbox WHERE tenant_id=? ORDER BY id DESC LIMIT ?",
            (tenant_id, limit)).fetchall()
    return [dict(row) for row in rows]


def acknowledge(path: str, tenant_id: str, notification_id: str, actor: str) -> tuple[int, dict]:
    at = datetime.now(UTC).isoformat()
    with _connect(path) as connection:
        row = connection.execute(
            "SELECT status FROM delivery_outbox WHERE tenant_id=? AND notification_id=?",
            (tenant_id, notification_id)).fetchone()
        if not row: return 404, {"code": "notification_not_found"}
        if row["status"] == "acknowledged": return 409, {"code": "notification_already_acknowledged"}
        connection.execute(
            "UPDATE delivery_outbox SET status='acknowledged',acknowledged_at=?,acknowledged_by=? WHERE tenant_id=? AND notification_id=?",
            (at, actor, tenant_id, notification_id))
    return 200, {"notification_id": notification_id, "status": "acknowledged",
                 "acknowledged_at": at, "acknowledged_by": actor,
                 "external_message_sent": False}


def create_schedule(path: str, request: ReportScheduleRequest) -> dict:
    schedule_id, created_at = str(uuid4()), datetime.now(UTC).isoformat()
    material = json.dumps(request.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    record_hash = hashlib.sha256(f"{schedule_id}\n{created_at}\n{material}".encode()).hexdigest()
    with _connect(path) as connection:
        cursor = connection.execute(
            "INSERT INTO delivery_report_schedules (schedule_id,created_at,tenant_id,report_type,interval_minutes,next_run_at,recipient_refs_json,owner,active,record_hash) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (schedule_id, created_at, request.tenant_id, request.report_type,
             request.interval_minutes, request.next_run_at.isoformat(),
             json.dumps(request.recipient_refs), request.owner, 1, record_hash))
    return {"id": cursor.lastrowid, "schedule_id": schedule_id, "created_at": created_at,
            "next_run_at": request.next_run_at.isoformat(), "record_hash": record_hash,
            "external_message_sent": False}


def schedules(path: str, tenant_id: str, limit: int = 100) -> list[dict]:
    with _connect(path) as connection:
        rows = connection.execute(
            "SELECT schedule_id,created_at,tenant_id,report_type,interval_minutes,next_run_at,recipient_refs_json,owner,active,record_hash FROM delivery_report_schedules WHERE tenant_id=? ORDER BY id DESC LIMIT ?",
            (tenant_id, limit),
        ).fetchall()
    return [
        {
            **{key: row[key] for key in row.keys() if key != "recipient_refs_json"},
            "recipient_refs": json.loads(row["recipient_refs_json"]),
            "active": bool(row["active"]),
        }
        for row in rows
    ]


def delivery_posture(path: str, tenant_id: str, secret_configured: bool) -> dict:
    with _connect(path) as connection:
        counts = {
            "subscriptions": connection.execute(
                "SELECT COUNT(*) FROM delivery_subscriptions WHERE tenant_id=? AND active=1",
                (tenant_id,),
            ).fetchone()[0],
            "events": connection.execute(
                "SELECT COUNT(*) FROM delivery_events WHERE tenant_id=?", (tenant_id,)
            ).fetchone()[0],
            "queued_notifications": connection.execute(
                "SELECT COUNT(*) FROM delivery_outbox WHERE tenant_id=? AND status='queued'",
                (tenant_id,),
            ).fetchone()[0],
            "report_schedules": connection.execute(
                "SELECT COUNT(*) FROM delivery_report_schedules WHERE tenant_id=? AND active=1",
                (tenant_id,),
            ).fetchone()[0],
        }
    return {
        "tenant_id": tenant_id,
        "webhook_authentication": "configured" if secret_configured else "blocked",
        "ready": secret_configured and counts["subscriptions"] > 0,
        "counts": counts,
        "delivery_mode": "durable_local_outbox",
        "external_delivery_enabled": False,
        "secrets_exposed": False,
    }


def run_due_reports(path: str, tenant_id: str, now: datetime | None = None) -> list[dict]:
    current = now or datetime.now(UTC); runs = []
    with _connect(path) as connection:
        rows = connection.execute(
            "SELECT * FROM delivery_report_schedules WHERE tenant_id=? AND active=1 AND next_run_at<=? ORDER BY id",
            (tenant_id, current.isoformat())).fetchall()
        for row in rows:
            run_id, created_at = str(uuid4()), current.isoformat()
            payload = {"tenant_id": tenant_id, "report_type": row["report_type"],
                       "scheduled_for": row["next_run_at"], "recipient_refs": json.loads(row["recipient_refs_json"])}
            payload_hash = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
            record_hash = hashlib.sha256(f"{run_id}\n{created_at}\n{payload_hash}".encode()).hexdigest()
            connection.execute(
                "INSERT INTO delivery_report_runs (run_id,created_at,tenant_id,schedule_id,report_type,recipient_refs_json,status,payload_hash,record_hash) VALUES(?,?,?,?,?,?,?,?,?)",
                (run_id, created_at, tenant_id, row["schedule_id"], row["report_type"],
                 row["recipient_refs_json"], "queued", payload_hash, record_hash))
            next_run = current + timedelta(minutes=row["interval_minutes"])
            connection.execute("UPDATE delivery_report_schedules SET next_run_at=? WHERE schedule_id=?",
                               (next_run.isoformat(), row["schedule_id"]))
            runs.append({"run_id": run_id, "schedule_id": row["schedule_id"],
                         "report_type": row["report_type"], "status": "queued",
                         "payload_hash": payload_hash, "record_hash": record_hash,
                         "next_run_at": next_run.isoformat(), "external_message_sent": False})
    return runs
