import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class RiskFactor(BaseModel):
    factor: str = Field(min_length=2, max_length=100)
    weight: int = Field(ge=0, le=100)
    triggered: bool
    evidence_ref: str = Field(min_length=2, max_length=200)
    explanation: str = Field(min_length=3, max_length=500)


class LinkedPattern(BaseModel):
    opaque_account_id: str = Field(min_length=3, max_length=100)
    relationship: str = Field(min_length=3, max_length=100)
    evidence_ref: str = Field(min_length=2, max_length=200)


class TransactionRiskEvidence(BaseModel):
    transaction_ref: str = Field(min_length=3, max_length=100)
    direction: Literal["deposit", "withdrawal"]
    asset: str = Field(pattern=r"^[A-Z0-9]{2,20}$")
    amount_bucket: str = Field(min_length=1, max_length=100)
    risk_indicators: list[str] = Field(default_factory=list, max_length=50)
    observed_at: datetime


class AMLCase(BaseModel):
    case_id: str = Field(min_length=3, max_length=100)
    status: Literal["open", "in_review", "escalated"]
    age_seconds: int = Field(ge=0)
    sla_seconds: int = Field(gt=0)
    factors: list[RiskFactor] = Field(min_length=1, max_length=100)
    linked_patterns: list[LinkedPattern] = Field(default_factory=list, max_length=100)
    transactions: list[TransactionRiskEvidence] = Field(default_factory=list, max_length=500)


class AMLAnalysisRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=100)
    observed_at: datetime
    evidence_refs: list[str] = Field(min_length=1, max_length=100)
    owner: str = Field(min_length=2, max_length=100)
    evidence_fresh: bool
    conflicting_fields: list[str] = Field(default_factory=list, max_length=100)
    cases: list[AMLCase] = Field(min_length=1, max_length=1000)


class AMLFeedbackRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=100)
    case_id: str = Field(min_length=3, max_length=100)
    reviewer: str = Field(min_length=2, max_length=100)
    outcome: Literal["confirmed", "false_positive", "needs_more_evidence"]
    correction: str = Field(default="", max_length=1000)


def analyze_aml(request: AMLAnalysisRequest) -> dict:
    now = datetime.now(UTC).isoformat()
    common = {
        "tenant_id": request.tenant_id, "observed_at": request.observed_at.isoformat(),
        "analyzed_at": now, "evidence_refs": request.evidence_refs,
        "owner": request.owner, "action_executed": False,
    }
    if not request.evidence_fresh or request.conflicting_fields:
        return {
            **common, "status": "blocked", "confidence": "none", "priority": "unknown",
            "cases": [], "limitations": (
                (["stale evidence"] if not request.evidence_fresh else []) +
                ([f"conflicting fields: {', '.join(request.conflicting_fields)}"]
                 if request.conflicting_fields else [])
            ),
            "recommended_next_action": "Refresh and reconcile case evidence.",
        }
    results = []
    for case in request.cases:
        score = min(100, sum(factor.weight for factor in case.factors if factor.triggered))
        priority = "critical" if score >= 80 or case.age_seconds > case.sla_seconds else (
            "high" if score >= 60 else "medium" if score >= 30 else "low"
        )
        triggered = [factor.model_dump() for factor in case.factors if factor.triggered]
        evidence_pack = {
            "transactions": [item.model_dump(mode="json") for item in case.transactions],
            "linked_accounts": [item.model_dump() for item in case.linked_patterns],
            "data_minimization": "Opaque identifiers and amount buckets only.",
        }
        results.append({
            "case_id": case.case_id, "status": case.status, "priority": priority,
            "score": score, "sla_breached": case.age_seconds > case.sla_seconds,
            "factors": triggered, "evidence_pack": evidence_pack,
            "case_note_draft": (
                f"Case {case.case_id} has priority {priority} from {len(triggered)} "
                "transparent factor(s). Review cited evidence; this is not a legal conclusion."
            ),
            "human_decision_required": True,
        })
    rank = {"critical": 4, "high": 3, "medium": 2, "low": 1}
    results.sort(key=lambda item: (rank[item["priority"]], item["score"]), reverse=True)
    counts = {priority: sum(item["priority"] == priority for item in results)
              for priority in ("critical", "high", "medium", "low")}
    overall = next((priority for priority in ("critical", "high", "medium", "low")
                    if counts[priority]), "low")
    return {
        **common, "status": "ready", "confidence": "high", "priority": overall,
        "cases": results,
        "queue_brief": {
            "total": len(results), "counts": counts,
            "sla_breaches": sum(item["sla_breached"] for item in results),
            "next_case_id": results[0]["case_id"],
        },
        "limitations": ["Priority assists human review and is not a final AML or legal judgment."],
        "recommended_next_action": "Review cases in ranked order and record the authorized outcome.",
    }


def _connect(path: str) -> sqlite3.Connection:
    database = Path(path)
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS xima_aml_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT, feedback_id TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL, tenant_id TEXT NOT NULL, case_id TEXT NOT NULL,
            reviewer TEXT NOT NULL, outcome TEXT NOT NULL, correction TEXT NOT NULL,
            previous_hash TEXT NOT NULL, record_hash TEXT NOT NULL UNIQUE
        )
        """
    )
    return connection


def record_aml_feedback(path: str, request: AMLFeedbackRequest) -> dict:
    feedback_id = str(uuid4())
    created_at = datetime.now(UTC).isoformat()
    with _connect(path) as connection:
        previous = connection.execute(
            "SELECT record_hash FROM xima_aml_feedback ORDER BY id DESC LIMIT 1"
        ).fetchone()
        previous_hash = previous["record_hash"] if previous else "0" * 64
        material = json.dumps(request.model_dump(), sort_keys=True, separators=(",", ":"))
        record_hash = hashlib.sha256(
            f"{previous_hash}\n{created_at}\n{feedback_id}\n{material}".encode()
        ).hexdigest()
        cursor = connection.execute(
            "INSERT INTO xima_aml_feedback "
            "(feedback_id,created_at,tenant_id,case_id,reviewer,outcome,correction,previous_hash,record_hash) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (feedback_id, created_at, request.tenant_id, request.case_id, request.reviewer,
             request.outcome, request.correction, previous_hash, record_hash),
        )
    return {
        "id": cursor.lastrowid, "feedback_id": feedback_id, "created_at": created_at,
        "tenant_id": request.tenant_id, "case_id": request.case_id,
        "outcome": request.outcome, "record_hash": record_hash,
        "exchange_write_performed": False,
    }
