import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


XimaDomain = Literal[
    "operations", "market_risk", "treasury", "aml_fraud", "security",
    "support", "knowledge", "governance",
]
DataClass = Literal["public", "internal", "confidential", "restricted"]


class EvidenceEnvelope(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=100)
    source_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{1,99}$")
    domain: XimaDomain
    schema_name: str = Field(pattern=r"^[a-z][a-z0-9._-]{1,99}$")
    schema_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    data_class: DataClass
    observed_at: datetime
    freshness_sla_seconds: int = Field(ge=1, le=604800)
    owner: str = Field(min_length=2, max_length=100)
    lineage: list[str] = Field(min_length=1, max_length=20)
    required_fields: list[str] = Field(default_factory=list, max_length=100)
    payload: dict = Field(min_length=1)

    @model_validator(mode="after")
    def validate_quality_boundary(self):
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at must include a timezone")
        if self.observed_at.astimezone(UTC) > datetime.now(UTC):
            raise ValueError("observed_at cannot be in the future")
        if len(set(self.required_fields)) != len(self.required_fields):
            raise ValueError("required_fields must be unique")
        return self


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _connect(path: str) -> sqlite3.Connection:
    database = Path(path)
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS xima_evidence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            evidence_id TEXT NOT NULL UNIQUE,
            tenant_id TEXT NOT NULL,
            source_id TEXT NOT NULL,
            domain TEXT NOT NULL,
            schema_name TEXT NOT NULL,
            schema_version TEXT NOT NULL,
            data_class TEXT NOT NULL,
            owner TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            ingested_at TEXT NOT NULL,
            freshness_sla_seconds INTEGER NOT NULL,
            lineage_json TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            quality_json TEXT NOT NULL,
            previous_hash TEXT NOT NULL,
            record_hash TEXT NOT NULL UNIQUE
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS xima_output_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT, output_id TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL, tenant_id TEXT NOT NULL, output_type TEXT NOT NULL,
            entity_id TEXT NOT NULL, payload_json TEXT NOT NULL, payload_hash TEXT NOT NULL,
            previous_hash TEXT NOT NULL, record_hash TEXT NOT NULL UNIQUE
        )
        """
    )
    return connection


def ingest_evidence(path: str, envelope: EvidenceEnvelope) -> tuple[int, dict]:
    now = datetime.now(UTC)
    observed = envelope.observed_at.astimezone(UTC)
    age_seconds = max(0, int((now - observed).total_seconds()))
    missing = [field for field in envelope.required_fields if field not in envelope.payload]
    null_fields = [field for field in envelope.required_fields if envelope.payload.get(field) is None]
    quality = {
        "valid": not missing and not null_fields,
        "missing_fields": missing,
        "null_fields": null_fields,
        "fresh": age_seconds <= envelope.freshness_sla_seconds,
        "age_seconds": age_seconds,
        "freshness_sla_seconds": envelope.freshness_sla_seconds,
    }
    if not quality["valid"]:
        return 422, {"code": "evidence_quality_failed", "quality": quality}

    evidence_id = str(uuid4())
    ingested_at = now.isoformat()
    payload_json = _canonical(envelope.payload)
    lineage_json = _canonical(envelope.lineage)
    quality_json = _canonical(quality)
    with _connect(path) as connection:
        previous = connection.execute(
            "SELECT record_hash FROM xima_evidence ORDER BY id DESC LIMIT 1"
        ).fetchone()
        previous_hash = previous["record_hash"] if previous else "0" * 64
        material = "\n".join((
            previous_hash, evidence_id, envelope.tenant_id, envelope.source_id,
            envelope.domain, envelope.schema_name, envelope.schema_version,
            observed.isoformat(), ingested_at, payload_json, quality_json,
        ))
        record_hash = hashlib.sha256(material.encode()).hexdigest()
        cursor = connection.execute(
            "INSERT INTO xima_evidence "
            "(evidence_id,tenant_id,source_id,domain,schema_name,schema_version,"
            "data_class,owner,observed_at,ingested_at,freshness_sla_seconds,"
            "lineage_json,payload_json,quality_json,previous_hash,record_hash) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (evidence_id, envelope.tenant_id, envelope.source_id, envelope.domain,
             envelope.schema_name, envelope.schema_version, envelope.data_class,
             envelope.owner, observed.isoformat(), ingested_at,
             envelope.freshness_sla_seconds, lineage_json, payload_json,
             quality_json, previous_hash, record_hash),
        )
    return 201, {
        "id": cursor.lastrowid, "evidence_id": evidence_id,
        "tenant_id": envelope.tenant_id, "source_id": envelope.source_id,
        "domain": envelope.domain, "schema": {
            "name": envelope.schema_name, "version": envelope.schema_version,
        },
        "observed_at": observed.isoformat(), "ingested_at": ingested_at,
        "quality": quality, "lineage": envelope.lineage,
        "record_hash": record_hash, "previous_hash": previous_hash,
        "action_executed": False,
    }


def source_health(path: str, tenant_id: str) -> dict:
    now = datetime.now(UTC)
    with _connect(path) as connection:
        rows = connection.execute(
            """
            SELECT e.* FROM xima_evidence e
            JOIN (
                SELECT source_id, MAX(id) AS latest_id FROM xima_evidence
                WHERE tenant_id=? GROUP BY source_id
            ) latest ON latest.latest_id=e.id
            ORDER BY e.source_id
            """, (tenant_id,),
        ).fetchall()
    sources = []
    for row in rows:
        age_seconds = max(0, int((now - datetime.fromisoformat(row["observed_at"])).total_seconds()))
        quality = json.loads(row["quality_json"])
        fresh = age_seconds <= row["freshness_sla_seconds"]
        sources.append({
            "source_id": row["source_id"], "domain": row["domain"],
            "owner": row["owner"], "schema": {
                "name": row["schema_name"], "version": row["schema_version"],
            },
            "observed_at": row["observed_at"], "age_seconds": age_seconds,
            "freshness_sla_seconds": row["freshness_sla_seconds"],
            "fresh": fresh, "quality_valid": quality["valid"],
            "status": "healthy" if fresh and quality["valid"] else "stale",
            "evidence_id": row["evidence_id"], "record_hash": row["record_hash"],
        })
    return {
        "tenant_id": tenant_id, "status": (
            "no_sources" if not sources else
            "healthy" if all(item["status"] == "healthy" for item in sources) else "degraded"
        ),
        "sources": sources, "checked_at": now.isoformat(), "action_executed": False,
    }


def replay_evidence(path: str, tenant_id: str, evidence_id: str) -> tuple[int, dict]:
    with _connect(path) as connection:
        row = connection.execute(
            "SELECT * FROM xima_evidence WHERE tenant_id=? AND evidence_id=?",
            (tenant_id, evidence_id),
        ).fetchone()
    if not row:
        return 404, {"code": "evidence_not_found"}
    return 200, {
        "evidence_id": row["evidence_id"], "tenant_id": row["tenant_id"],
        "source_id": row["source_id"], "domain": row["domain"],
        "schema": {"name": row["schema_name"], "version": row["schema_version"]},
        "data_class": row["data_class"], "owner": row["owner"],
        "observed_at": row["observed_at"], "ingested_at": row["ingested_at"],
        "lineage": json.loads(row["lineage_json"]),
        "payload": json.loads(row["payload_json"]),
        "quality": json.loads(row["quality_json"]),
        "record_hash": row["record_hash"], "previous_hash": row["previous_hash"],
        "replayed": True, "action_executed": False,
    }


def verify_xima_chain(path: str) -> dict:
    with _connect(path) as connection:
        rows = connection.execute("SELECT * FROM xima_evidence ORDER BY id").fetchall()
    previous_hash = "0" * 64
    for row in rows:
        material = "\n".join((
            previous_hash, row["evidence_id"], row["tenant_id"], row["source_id"],
            row["domain"], row["schema_name"], row["schema_version"],
            row["observed_at"], row["ingested_at"], row["payload_json"],
            row["quality_json"],
        ))
        expected = hashlib.sha256(material.encode()).hexdigest()
        if row["previous_hash"] != previous_hash or row["record_hash"] != expected:
            return {"valid": False, "records": len(rows), "failed_id": row["id"]}
        previous_hash = row["record_hash"]
    return {"valid": True, "records": len(rows), "head_hash": previous_hash}


def record_xima_output(
    path: str, tenant_id: str, output_type: str, entity_id: str, payload: dict,
) -> dict:
    output_id = str(uuid4())
    created_at = datetime.now(UTC).isoformat()
    payload_json = _canonical(payload)
    payload_hash = hashlib.sha256(payload_json.encode()).hexdigest()
    with _connect(path) as connection:
        previous = connection.execute(
            "SELECT record_hash FROM xima_output_audit ORDER BY id DESC LIMIT 1"
        ).fetchone()
        previous_hash = previous["record_hash"] if previous else "0" * 64
        material = "\n".join((previous_hash, output_id, created_at, tenant_id,
                               output_type, entity_id, payload_hash))
        record_hash = hashlib.sha256(material.encode()).hexdigest()
        cursor = connection.execute(
            "INSERT INTO xima_output_audit "
            "(output_id,created_at,tenant_id,output_type,entity_id,payload_json,payload_hash,"
            "previous_hash,record_hash) VALUES(?,?,?,?,?,?,?,?,?)",
            (output_id, created_at, tenant_id, output_type, entity_id, payload_json,
             payload_hash, previous_hash, record_hash),
        )
    return {
        "id": cursor.lastrowid, "output_id": output_id, "created_at": created_at,
        "payload_hash": payload_hash, "record_hash": record_hash,
    }


def recent_xima_outputs(path: str, tenant_id: str, limit: int) -> list[dict]:
    with _connect(path) as connection:
        rows = connection.execute(
            "SELECT id,output_id,created_at,tenant_id,output_type,entity_id,payload_hash,"
            "previous_hash,record_hash FROM xima_output_audit WHERE tenant_id=? "
            "ORDER BY id DESC LIMIT ?", (tenant_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def verify_xima_output_chain(path: str) -> dict:
    with _connect(path) as connection:
        rows = connection.execute("SELECT * FROM xima_output_audit ORDER BY id").fetchall()
    previous_hash = "0" * 64
    for row in rows:
        payload_hash = hashlib.sha256(row["payload_json"].encode()).hexdigest()
        material = "\n".join((previous_hash, row["output_id"], row["created_at"],
                               row["tenant_id"], row["output_type"], row["entity_id"],
                               payload_hash))
        expected = hashlib.sha256(material.encode()).hexdigest()
        if (row["payload_hash"] != payload_hash or row["previous_hash"] != previous_hash
                or row["record_hash"] != expected):
            return {"valid": False, "records": len(rows), "failed_id": row["id"]}
        previous_hash = row["record_hash"]
    return {"valid": True, "records": len(rows), "head_hash": previous_hash}
