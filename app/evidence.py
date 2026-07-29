import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path


GENESIS_HASH = "0" * 64


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _connect(path: str) -> sqlite3.Connection:
    database = Path(path)
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS evidence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            collected_at TEXT NOT NULL,
            mode TEXT NOT NULL,
            market TEXT NOT NULL,
            pending_withdrawals INTEGER NOT NULL,
            incident_severity TEXT NOT NULL,
            market_risk_severity TEXT NOT NULL,
            source_generated_at TEXT,
            payload_json TEXT NOT NULL,
            previous_hash TEXT NOT NULL,
            record_hash TEXT NOT NULL UNIQUE
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            report_id TEXT NOT NULL,
            rating TEXT NOT NULL,
            comment TEXT NOT NULL,
            feedback_hash TEXT NOT NULL UNIQUE
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS access_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            role TEXT NOT NULL,
            capability TEXT NOT NULL,
            allowed INTEGER NOT NULL,
            enforced INTEGER NOT NULL,
            reason TEXT NOT NULL,
            decision_hash TEXT NOT NULL UNIQUE
        )
        """
    )
    return connection


def record_dashboard(path: str, payload: dict) -> dict:
    """Append aggregate evidence to a SHA-256 hash chain."""
    operations = payload["operations"]
    market = payload["market"]
    incident = payload["incident"]
    risk = payload["market_risk"]
    collected_at = datetime.now(UTC).isoformat()
    safe_payload = {
        "version": payload["version"],
        "mode": payload["mode"],
        "operations": operations,
        "market": market,
        "incident": incident,
        "market_risk": risk,
    }
    payload_json = _canonical(safe_payload)

    with _connect(path) as connection:
        previous = connection.execute(
            "SELECT record_hash FROM evidence ORDER BY id DESC LIMIT 1"
        ).fetchone()
        previous_hash = previous["record_hash"] if previous else GENESIS_HASH
        material = f"{previous_hash}\n{collected_at}\n{payload_json}"
        record_hash = hashlib.sha256(material.encode()).hexdigest()
        cursor = connection.execute(
            """
            INSERT INTO evidence (
                collected_at, mode, market, pending_withdrawals,
                incident_severity, market_risk_severity, source_generated_at,
                payload_json, previous_hash, record_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                collected_at,
                payload["mode"],
                market.get("data", {}).get("market", "unknown"),
                int(operations.get("data", {}).get("pending_withdrawals", 0)),
                incident["severity"],
                risk["severity"],
                operations.get("meta", {}).get("generated_at"),
                payload_json,
                previous_hash,
                record_hash,
            ),
        )
        return {
            "id": cursor.lastrowid,
            "collected_at": collected_at,
            "record_hash": record_hash,
        }


def recent_evidence(path: str, limit: int) -> list[dict]:
    with _connect(path) as connection:
        rows = connection.execute(
            """
            SELECT id, collected_at, mode, market, pending_withdrawals,
                   incident_severity, market_risk_severity,
                   source_generated_at, record_hash
            FROM evidence ORDER BY id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def latest_evidence_payload(path: str) -> dict | None:
    with _connect(path) as connection:
        row = connection.execute(
            "SELECT id, collected_at, record_hash, payload_json "
            "FROM evidence ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "collected_at": row["collected_at"],
        "record_hash": row["record_hash"],
        "payload": json.loads(row["payload_json"]),
    }


def verify_chain(path: str) -> dict:
    with _connect(path) as connection:
        rows = connection.execute("SELECT * FROM evidence ORDER BY id").fetchall()
    expected_previous = GENESIS_HASH
    for row in rows:
        material = f"{row['previous_hash']}\n{row['collected_at']}\n{row['payload_json']}"
        expected_hash = hashlib.sha256(material.encode()).hexdigest()
        if row["previous_hash"] != expected_previous or row["record_hash"] != expected_hash:
            return {"valid": False, "records": len(rows), "failed_at_id": row["id"]}
        expected_previous = row["record_hash"]
    return {
        "valid": True,
        "records": len(rows),
        "head_hash": expected_previous if rows else GENESIS_HASH,
        "verified_at": datetime.now(UTC).isoformat(),
    }


def _as_decimal(value: object) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def evidence_trends(path: str, limit: int, freshness_warning_seconds: int) -> dict:
    """Compare the oldest and newest records in a bounded evidence window."""
    with _connect(path) as connection:
        rows = connection.execute(
            "SELECT * FROM evidence ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    rows = list(reversed(rows))
    if not rows:
        return {"records": 0, "status": "insufficient", "alerts": []}

    oldest = json.loads(rows[0]["payload_json"])
    newest = json.loads(rows[-1]["payload_json"])
    old_ops = oldest["operations"]["data"]
    new_ops = newest["operations"]["data"]
    deltas = {
        field: int(new_ops.get(field, 0)) - int(old_ops.get(field, 0))
        for field in ("orders", "deposits", "withdrawals", "pending_withdrawals")
    }

    old_last = _as_decimal(oldest["market"]["data"].get("last"))
    new_last = _as_decimal(newest["market"]["data"].get("last"))
    price_change_percent = None
    if old_last is not None and new_last is not None and old_last > 0:
        price_change_percent = str(
            ((new_last - old_last) / old_last * 100).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        )

    freshness = newest["operations"].get("meta", {}).get(
        "data_freshness_seconds"
    )
    alerts = []
    if freshness is None:
        alerts.append(
            {"severity": "warning", "code": "freshness_unknown", "observed": None}
        )
    elif int(freshness) > freshness_warning_seconds:
        alerts.append(
            {
                "severity": "warning",
                "code": "operations_evidence_stale",
                "observed": int(freshness),
                "threshold": freshness_warning_seconds,
            }
        )

    return {
        "records": len(rows),
        "status": "ready" if len(rows) >= 2 else "insufficient",
        "window": {
            "from_record_id": rows[0]["id"],
            "to_record_id": rows[-1]["id"],
            "from": rows[0]["collected_at"],
            "to": rows[-1]["collected_at"],
        },
        "deltas": deltas,
        "market": {
            "symbol": newest["market"]["data"].get("market"),
            "last_price_change_percent": price_change_percent,
        },
        "freshness": {
            "operations_seconds": freshness,
            "warning_threshold_seconds": freshness_warning_seconds,
        },
        "alerts": alerts,
        "limitations": [
            "Trends reflect dashboard collection times, not a fixed sampling schedule.",
            "Aggregate deltas do not identify affected users, assets or networks.",
        ],
        "action_executed": False,
    }


def record_feedback(path: str, report_id: str, rating: str, comment: str) -> dict:
    created_at = datetime.now(UTC).isoformat()
    material = _canonical(
        {
            "created_at": created_at,
            "report_id": report_id,
            "rating": rating,
            "comment": comment,
        }
    )
    feedback_hash = hashlib.sha256(material.encode()).hexdigest()
    with _connect(path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO feedback (created_at, report_id, rating, comment, feedback_hash)
            VALUES (?, ?, ?, ?, ?)
            """,
            (created_at, report_id, rating, comment, feedback_hash),
        )
    return {
        "id": cursor.lastrowid,
        "created_at": created_at,
        "report_id": report_id,
        "rating": rating,
        "feedback_hash": feedback_hash,
        "local_only": True,
    }


def feedback_summary(path: str) -> dict:
    with _connect(path) as connection:
        rows = connection.execute(
            "SELECT rating, COUNT(*) AS count FROM feedback GROUP BY rating"
        ).fetchall()
    counts = {row["rating"]: row["count"] for row in rows}
    return {"total": sum(counts.values()), "counts": counts}


def record_access_decision(path: str, decision: dict) -> dict:
    created_at = datetime.now(UTC).isoformat()
    material = _canonical({"created_at": created_at, **decision})
    decision_hash = hashlib.sha256(material.encode()).hexdigest()
    with _connect(path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO access_audit (
                created_at, role, capability, allowed, enforced, reason, decision_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                created_at,
                decision["role"],
                decision["capability"],
                int(decision["allowed"]),
                int(decision["enforced"]),
                decision["reason"],
                decision_hash,
            ),
        )
    return {
        "id": cursor.lastrowid,
        "created_at": created_at,
        "decision_hash": decision_hash,
    }


def recent_access_decisions(path: str, limit: int) -> list[dict]:
    with _connect(path) as connection:
        rows = connection.execute(
            """
            SELECT id, created_at, role, capability, allowed, enforced,
                   reason, decision_hash
            FROM access_audit ORDER BY id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [
        {
            **dict(row),
            "allowed": bool(row["allowed"]),
            "enforced": bool(row["enforced"]),
        }
        for row in rows
        ]


def backup_and_verify(source_path: str, backup_path: str) -> dict:
    """Create a consistent SQLite backup and verify its evidence hash chain."""
    source = Path(source_path)
    target = Path(backup_path)
    if not source.exists():
        raise FileNotFoundError(f"Evidence database does not exist: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source) as source_connection:
        with sqlite3.connect(target) as target_connection:
            source_connection.backup(target_connection)
    verification = verify_chain(str(target))
    return {
        "backup_path": str(target),
        "created_at": datetime.now(UTC).isoformat(),
        "restorable": verification["valid"],
        "evidence_records": verification["records"],
        "integrity": verification,
    }
