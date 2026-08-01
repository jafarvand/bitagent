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


class RetentionPlanRequest(BaseModel):
    segment: str = Field(min_length=3, max_length=200)
    lifecycle_stage: Literal["registered", "verifying", "activating", "active", "at_risk", "dormant"]
    tenant_id: str = Field(min_length=1, max_length=100)
    evidence: list[str] = Field(min_length=1, max_length=20)
    consented: bool
    suppressed: bool
    messages_last_7_days: int = Field(ge=0, le=1000)
    frequency_cap_7_days: int = Field(ge=1, le=100)
    target_metric: str = Field(min_length=2, max_length=120)
    target_improvement_percent: float = Field(gt=0, le=100)
    owner: str = Field(min_length=2, max_length=100)


class ContentStudioRequest(BaseModel):
    campaign_id: str = Field(min_length=3, max_length=100)
    product: str = Field(min_length=2, max_length=120)
    audience: str = Field(min_length=3, max_length=200)
    channels: list[Literal["email", "social", "content", "partner", "referral", "paid"]] = Field(
        min_length=1, max_length=6
    )
    value_proposition: str = Field(min_length=3, max_length=500)
    cta: str = Field(min_length=2, max_length=120)
    claims: list[str] = Field(default_factory=list, max_length=20)
    claim_sources: list[str] = Field(default_factory=list, max_length=20)
    language: str = Field(default="en", min_length=2, max_length=12)
    native_speaker_approved: bool = False
    scheduled_for: datetime
    approval_due_at: datetime


class VariantMetric(BaseModel):
    name: str = Field(min_length=1, max_length=20)
    assigned: int = Field(ge=0)
    conversions: int = Field(ge=0)

    @model_validator(mode="after")
    def conversions_do_not_exceed_sample(self):
        if self.conversions > self.assigned:
            raise ValueError("conversions cannot exceed assigned sample")
        return self


class MeasurementRequest(BaseModel):
    campaign_id: str = Field(min_length=3, max_length=100)
    impressions: int = Field(ge=0)
    visits: int = Field(ge=0)
    registrations: int = Field(ge=0)
    activations: int = Field(ge=0)
    retained: int = Field(ge=0)
    spend: float = Field(ge=0)
    opt_outs: int = Field(ge=0)
    complaints: int = Field(ge=0)
    delivered: int = Field(ge=0)
    variants: list[VariantMetric] = Field(min_length=2, max_length=10)
    attribution_model: Literal["last_touch", "first_touch", "unattributed"]
    minimum_sample_per_variant: int = Field(default=100, ge=10, le=1_000_000)


def build_measurement(path: str, request: MeasurementRequest) -> dict:
    report_id = str(uuid4())
    def rate(numerator: int, denominator: int) -> float | None:
        return round(numerator / denominator * 100, 2) if denominator else None

    total_assigned = sum(item.assigned for item in request.variants)
    expected = total_assigned / len(request.variants) if request.variants else 0
    srm = bool(expected) and any(
        abs(item.assigned - expected) / expected > 0.10 for item in request.variants
    )
    premature = any(item.assigned < request.minimum_sample_per_variant for item in request.variants)
    variant_results = [
        {
            **item.model_dump(),
            "conversion_rate_percent": rate(item.conversions, item.assigned),
        }
        for item in request.variants
    ]
    complaint_rate = rate(request.complaints, request.delivered)
    opt_out_rate = rate(request.opt_outs, request.delivered)
    guardrails = {
        "complaint_rate_percent": complaint_rate,
        "complaint_rate_ok": complaint_rate is not None and complaint_rate <= 0.1,
        "opt_out_rate_percent": opt_out_rate,
        "opt_out_rate_ok": opt_out_rate is not None and opt_out_rate <= 1.0,
        "spend_nonnegative": request.spend >= 0,
    }
    if not all(guardrails[key] for key in ("complaint_rate_ok", "opt_out_rate_ok", "spend_nonnegative")):
        recommendation = "stop"
    elif srm or premature:
        recommendation = "change"
    else:
        recommendation = "keep"
    report = {
        "id": report_id,
        "campaign_id": request.campaign_id,
        "funnel": {
            "impression_to_visit_percent": rate(request.visits, request.impressions),
            "visit_to_registration_percent": rate(request.registrations, request.visits),
            "registration_to_activation_percent": rate(request.activations, request.registrations),
            "activation_to_retained_percent": rate(request.retained, request.activations),
        },
        "attribution": {
            "model": request.attribution_model,
            "boundary": "Directional aggregate attribution; not causal proof.",
            "uncertainty": "Channel overlap and unobserved touchpoints are not resolved.",
        },
        "experiment": {
            "variants": variant_results,
            "sample_ratio_mismatch": srm,
            "premature": premature,
            "minimum_sample_per_variant": request.minimum_sample_per_variant,
        },
        "guardrails": guardrails,
        "performance_brief": {
            "recommendation": recommendation,
            "reason": "Guardrails take priority; otherwise experiment validity controls the decision.",
        },
        "action_executed": False,
    }
    report["audit"] = record_event(path, "measurement_report_created", report_id, report)
    return report


def build_content_studio(path: str, request: ContentStudioRequest) -> dict:
    artifact_id = str(uuid4())
    prohibited_terms = ("guaranteed profit", "risk-free", "act now or lose", "secret strategy")
    combined_claims = " ".join(request.claims).lower()
    checks = {
        "brand": not any(term in combined_claims for term in prohibited_terms),
        "claims_substantiated": not request.claims or bool(request.claim_sources),
        "privacy": "sensitive trait" not in request.audience.lower(),
        "localization": request.language == "en" or request.native_speaker_approved,
        "calendar_dependency": request.approval_due_at < request.scheduled_for,
    }
    passed = all(checks.values())
    variants = []
    for channel in request.channels:
        variants.extend(
            {
                "channel": channel,
                "variant": label,
                "copy": f"{request.value_proposition} {request.cta}",
                "status": "draft" if passed else "blocked",
            }
            for label in ("A", "B")
        )
    artifact = {
        "id": artifact_id,
        **request.model_dump(mode="json"),
        "variants": variants,
        "validation": {"passed": passed, "checks": checks},
        "calendar": {
            "approval_due_at": request.approval_due_at.isoformat(),
            "scheduled_for": request.scheduled_for.isoformat(),
            "dependencies_satisfied": checks["calendar_dependency"],
        },
        "status": "draft" if passed else "blocked",
        "approval_required": True,
        "publish_enabled": False,
    }
    artifact["audit"] = record_event(path, "content_artifact_created", artifact_id, artifact)
    return artifact


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


def build_retention_plan(path: str, request: RetentionPlanRequest) -> dict:
    plan_id = str(uuid4())
    checks = {
        "consent": request.consented,
        "not_suppressed": not request.suppressed,
        "within_frequency_cap": request.messages_last_7_days < request.frequency_cap_7_days,
    }
    eligible = all(checks.values())
    programs = {
        "registered": ("onboarding", "Complete verification education"),
        "verifying": ("onboarding", "Resolve approved verification guidance gaps"),
        "activating": ("activation", "Explain first successful use"),
        "active": ("adoption", "Teach one relevant approved feature"),
        "at_risk": ("retention", "Offer helpful product education"),
        "dormant": ("reengagement", "Invite a consented return without pressure"),
    }
    program, message = programs[request.lifecycle_stage]
    plan = {
        "id": plan_id,
        "type": "retention",
        **request.model_dump(),
        "program": program,
        "content_brief": {
            "message": message,
            "cta": "Review approved guidance",
            "status": "draft" if eligible else "blocked",
            "incentive": None,
        },
        "eligibility": {"eligible": eligible, "checks": checks, "fail_closed": True},
        "kpi_target": {
            "metric": request.target_metric,
            "improvement_percent": request.target_improvement_percent,
        },
        "status": "draft" if eligible else "blocked",
        "approval_required": True,
        "external_execution_enabled": False,
    }
    plan["audit"] = record_event(path, "retention_plan_created", plan_id, plan)
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
