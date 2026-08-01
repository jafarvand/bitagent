from datetime import UTC, datetime

from pydantic import AwareDatetime, BaseModel, Field


class ShadowOutcome(BaseModel):
    outcome_id: str = Field(min_length=2, max_length=100)
    alert_key: str = Field(min_length=2, max_length=100)
    predicted_material: bool
    actual_material: bool
    workflow_latency_ms: int = Field(ge=0)


class ScheduledReportOutcome(BaseModel):
    report_id: str = Field(min_length=2, max_length=100)
    generated_within_sla: bool


class ReliabilityEvidence(BaseModel):
    load_test_passed: bool
    soak_test_passed: bool
    failover_test_passed: bool
    backup_restore_passed: bool
    monitoring_verified: bool
    on_call_runbook_ref: str | None = Field(default=None, max_length=500)
    escalation_runbook_ref: str | None = Field(default=None, max_length=500)
    training_record_refs: list[str] = Field(default_factory=list, max_length=100)
    acceptance_roles: list[str] = Field(default_factory=list, max_length=100)


class ShadowPilotRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=100)
    window_start: AwareDatetime
    window_end: AwareDatetime
    evidence_refs: list[str] = Field(min_length=1, max_length=100)
    owner: str = Field(min_length=2, max_length=100)
    outcomes: list[ShadowOutcome] = Field(min_length=1, max_length=100000)
    scheduled_reports: list[ScheduledReportOutcome] = Field(min_length=1, max_length=100000)
    reliability: ReliabilityEvidence
    target_precision_percent: float = Field(default=80, ge=0, le=100)
    target_recall_percent: float = Field(default=90, ge=0, le=100)
    maximum_duplicate_percent: float = Field(default=10, ge=0, le=100)
    target_report_success_percent: float = Field(default=95, ge=0, le=100)
    maximum_p95_latency_ms: int = Field(default=5000, gt=0)


REQUIRED_ACCEPTANCE_ROLES = {
    "operations", "risk", "treasury", "aml", "security", "support",
    "privacy", "compliance",
}


def evaluate_shadow_pilot(request: ShadowPilotRequest) -> dict:
    true_positive = sum(item.predicted_material and item.actual_material for item in request.outcomes)
    false_positive = sum(item.predicted_material and not item.actual_material for item in request.outcomes)
    false_negative = sum(not item.predicted_material and item.actual_material for item in request.outcomes)
    true_negative = sum(not item.predicted_material and not item.actual_material for item in request.outcomes)
    predicted_positive = true_positive + false_positive
    actual_positive = true_positive + false_negative
    precision = true_positive / predicted_positive * 100 if predicted_positive else 100.0
    recall = true_positive / actual_positive * 100 if actual_positive else 100.0
    alert_keys = [item.alert_key for item in request.outcomes if item.predicted_material]
    duplicate_count = len(alert_keys) - len(set(alert_keys))
    duplicate_percent = duplicate_count / len(alert_keys) * 100 if alert_keys else 0.0
    report_success = (
        sum(item.generated_within_sla for item in request.scheduled_reports) /
        len(request.scheduled_reports) * 100
    )
    latencies = sorted(item.workflow_latency_ms for item in request.outcomes)
    p95_index = max(0, _ceil(len(latencies) * 0.95) - 1)
    p95_latency = latencies[p95_index]
    reliability = request.reliability
    missing_roles = sorted(REQUIRED_ACCEPTANCE_ROLES - set(reliability.acceptance_roles))
    gates = {
        "precision": precision >= request.target_precision_percent,
        "recall": recall >= request.target_recall_percent,
        "duplicates": duplicate_percent <= request.maximum_duplicate_percent,
        "scheduled_reports": report_success >= request.target_report_success_percent,
        "latency": p95_latency <= request.maximum_p95_latency_ms,
        "load": reliability.load_test_passed,
        "soak": reliability.soak_test_passed,
        "failover": reliability.failover_test_passed,
        "backup_restore": reliability.backup_restore_passed,
        "monitoring": reliability.monitoring_verified,
        "runbooks": bool(reliability.on_call_runbook_ref and reliability.escalation_runbook_ref),
        "training": bool(reliability.training_record_refs),
        "domain_acceptance": not missing_roles,
    }
    ready = all(gates.values())
    noisy_keys = sorted({key for key in alert_keys if alert_keys.count(key) > 1})
    return {
        "tenant_id": request.tenant_id,
        "window": {"start": request.window_start.isoformat(), "end": request.window_end.isoformat()},
        "evaluated_at": datetime.now(UTC).isoformat(), "evidence_refs": request.evidence_refs,
        "owner": request.owner, "status": "ready" if ready else "not_ready",
        "decision": "eligible_for_production_limited_review" if ready else "remain_in_shadow_mode",
        "metrics": {
            "true_positive": true_positive, "false_positive": false_positive,
            "false_negative": false_negative, "true_negative": true_negative,
            "precision_percent": round(precision, 2), "recall_percent": round(recall, 2),
            "duplicate_count": duplicate_count,
            "duplicate_percent": round(duplicate_percent, 2),
            "scheduled_report_success_percent": round(report_success, 2),
            "p95_workflow_latency_ms": p95_latency,
        },
        "noise": {"duplicate_alert_keys": noisy_keys},
        "reliability": reliability.model_dump(), "gates": gates,
        "missing_acceptance_roles": missing_roles,
        "external_approval_still_required": True,
        "limitations": [
            "This evaluates submitted pilot evidence and does not launch production.",
            "Steering, security and compliance approval remains external and mandatory.",
        ],
        "recommended_next_action": (
            "Submit evidence package for production-limited owner review."
            if ready else "Remediate failed gates and continue shadow measurement."
        ),
        "action_executed": False,
    }


def _ceil(value: float) -> int:
    integer = int(value)
    return integer if value == integer else integer + 1
