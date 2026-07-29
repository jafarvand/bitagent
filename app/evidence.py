import hashlib
import json
import sqlite3
from datetime import UTC, datetime
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
