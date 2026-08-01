import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


MarketingObjective = Literal["acquisition", "retention", "reactivation"]

GOVERNANCE = {
    "version": "1.0.0",
    "owners": ["marketing", "privacy", "compliance", "data", "security"],
    "permitted_data": [
        "consent_status", "lifecycle_stage", "aggregate_campaign_events",
        "approved_channel_preferences", "tenant_id",
    ],
    "prohibited_data": [
        "wallet_balance", "trading_history", "protected_or_sensitive_traits",
        "inferred_vulnerability",
    ],
    "required_controls": [
        "tenant_isolation", "consent", "suppression", "purpose_limitation",
        "retention", "right_to_erasure", "human_approval_before_execution",
    ],
    "external_execution_default": "disabled",
}

LIFECYCLE_STAGES = (
    "prospect", "registered", "verifying", "activating", "active",
    "at_risk", "dormant", "reactivated",
)

EVENT_TAXONOMY = {
    "awareness": ("content_viewed", "ad_clicked"),
    "acquisition": ("registration_started", "registration_completed"),
    "activation": ("verification_completed", "first_funding", "first_successful_use"),
    "retention": ("feature_adopted", "repeat_use"),
    "reactivation": ("reengagement_engaged", "user_reactivated"),
    "safety": ("opt_out", "complaint", "suppressed"),
}


class CampaignPlanRequest(BaseModel):
    name: str = Field(min_length=3, max_length=120)
    objective: MarketingObjective
    audience: str = Field(min_length=3, max_length=200)
    channel: Literal["email", "social", "content", "partner", "referral", "paid"]
    customer_promise: str = Field(min_length=3, max_length=500)
    owner: str = Field(min_length=2, max_length=100)
    kpi: str = Field(min_length=2, max_length=120)
    budget_ceiling: str = Field(pattern=r"^\d+(\.\d{1,2})?$")
    stop_conditions: list[str] = Field(min_length=1, max_length=10)
    evidence: list[str] = Field(min_length=1, max_length=20)
    assumptions: list[str] = Field(default_factory=list, max_length=20)
    consent_basis: str = Field(min_length=3, max_length=200)
    tenant_id: str = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def require_bounded_plan(self):
        if any(not item.strip() for item in self.stop_conditions + self.evidence):
            raise ValueError("stop conditions and evidence must be non-empty")
        return self


class AcquisitionPlanRequest(BaseModel):
    product: str = Field(min_length=2, max_length=120)
    segment: str = Field(min_length=3, max_length=200)
    tenant_id: str = Field(min_length=1, max_length=100)
    evidence: list[str] = Field(min_length=1, max_length=20)
    channels: list[Literal["email", "social", "content", "partner", "referral", "paid"]] = Field(
        min_length=1, max_length=6
    )
    target_qualified_visitors: int = Field(gt=0, le=10_000_000)
    target_registration_rate_percent: float = Field(gt=0, le=100)
    target_activation_rate_percent: float = Field(gt=0, le=100)
    owner: str = Field(min_length=2, max_length=100)


def build_acquisition_plan(path: str, request: AcquisitionPlanRequest) -> dict:
    plan_id = str(uuid4())
    registrations = round(
        request.target_qualified_visitors * request.target_registration_rate_percent / 100
    )
    activations = round(registrations * request.target_activation_rate_percent / 100)
    funnel = [
        {"stage": "qualified_visit", "target": request.target_qualified_visitors},
        {"stage": "registration_completed", "target": registrations},
        {"stage": "verification_completed", "target": registrations},
        {"stage": "first_successful_use", "target": activations},
    ]
    briefs = [
        {
            "channel": channel,
            "objective": "Move consented qualified prospects to first successful use",
            "audience": request.segment,
            "message": f"Evidence-backed introduction to {request.product}",
            "cta": "Review the approved product guide",
            "status": "draft",
            "claims_require_sources": True,
        }
        for channel in request.channels
    ]
    plan = {
        "id": plan_id,
        "type": "acquisition",
        **request.model_dump(),
        "funnel": funnel,
        "kpi_targets": {
            "qualified_visitors": request.target_qualified_visitors,
            "registrations": registrations,
            "activated_customers": activations,
            "registration_rate_percent": request.target_registration_rate_percent,
            "activation_rate_percent": request.target_activation_rate_percent,
        },
        "content_briefs": briefs,
        "assumptions": [
            "Targets are planning estimates, not forecasts.",
            "Only consented, non-suppressed prospects may be included.",
        ],
        "status": "draft",
        "approval_required": True,
        "external_execution_enabled": False,
    }
    plan["audit"] = record_event(path, "acquisition_plan_created", plan_id, plan)
    return plan


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _connect(path: str) -> sqlite3.Connection:
    database = Path(path)
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS marketing_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            event_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            previous_hash TEXT NOT NULL,
            record_hash TEXT NOT NULL UNIQUE
        )
        """
    )
    return connection


def record_event(path: str, event_type: str, entity_id: str, payload: dict) -> dict:
    created_at = datetime.now(UTC).isoformat()
    payload_json = _canonical(payload)
    with _connect(path) as connection:
        previous = connection.execute(
            "SELECT record_hash FROM marketing_audit ORDER BY id DESC LIMIT 1"
        ).fetchone()
        previous_hash = previous["record_hash"] if previous else "0" * 64
        material = f"{previous_hash}\n{created_at}\n{event_type}\n{entity_id}\n{payload_json}"
        record_hash = hashlib.sha256(material.encode()).hexdigest()
        cursor = connection.execute(
            "INSERT INTO marketing_audit "
            "(created_at,event_type,entity_id,payload_json,previous_hash,record_hash) "
            "VALUES (?,?,?,?,?,?)",
            (created_at, event_type, entity_id, payload_json, previous_hash, record_hash),
        )
    return {"id": cursor.lastrowid, "created_at": created_at, "record_hash": record_hash}


def audit_events(path: str, limit: int = 50) -> list[dict]:
    with _connect(path) as connection:
        rows = connection.execute(
            "SELECT id,created_at,event_type,entity_id,previous_hash,record_hash "
            "FROM marketing_audit ORDER BY id DESC LIMIT ?", (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def create_plan(path: str, request: CampaignPlanRequest) -> dict:
    plan_id = str(uuid4())
    plan = {
        "id": plan_id,
        **request.model_dump(),
        "status": "draft",
        "approval_required": True,
        "external_execution_enabled": False,
        "created_at": datetime.now(UTC).isoformat(),
    }
    plan["audit"] = record_event(path, "plan_created", plan_id, plan)
    return plan
