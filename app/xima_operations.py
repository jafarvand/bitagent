import hashlib
import json
from datetime import UTC, datetime

from pydantic import BaseModel, Field


class ServiceMetric(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    error_rate_percent: float = Field(ge=0, le=100)
    p95_latency_ms: int = Field(ge=0, le=3_600_000)
    capacity_used_percent: float = Field(ge=0, le=100)
    dependencies_healthy: bool


class QueueMetric(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    backlog: int = Field(ge=0)
    oldest_age_seconds: int = Field(ge=0)
    throughput_per_minute: float = Field(ge=0)


class WorkerMetric(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    heartbeat_age_seconds: int = Field(ge=0)
    available_workers: int = Field(ge=0)


class OperationsAnalysisRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=100)
    observed_at: datetime
    evidence_refs: list[str] = Field(min_length=1, max_length=100)
    owner: str = Field(min_length=2, max_length=100)
    evidence_fresh: bool
    conflicting_fields: list[str] = Field(default_factory=list, max_length=100)
    services: list[ServiceMetric] = Field(min_length=1, max_length=100)
    queues: list[QueueMetric] = Field(default_factory=list, max_length=100)
    workers: list[WorkerMetric] = Field(default_factory=list, max_length=100)
    similar_incident_ids: list[str] = Field(default_factory=list, max_length=20)


_SEVERITY_RANK = {"healthy": 0, "warning": 1, "critical": 2}


def analyze_operations(request: OperationsAnalysisRequest) -> dict:
    analyzed_at = datetime.now(UTC).isoformat()
    if not request.evidence_fresh or request.conflicting_fields:
        return {
            "tenant_id": request.tenant_id, "status": "blocked",
            "severity": "unknown", "confidence": "none",
            "observed_at": request.observed_at.isoformat(), "analyzed_at": analyzed_at,
            "evidence_refs": request.evidence_refs, "owner": request.owner,
            "findings": [], "limitations": (
                (["stale evidence"] if not request.evidence_fresh else []) +
                ([f"conflicting fields: {', '.join(request.conflicting_fields)}"]
                 if request.conflicting_fields else [])
            ),
            "recommended_next_action": "Refresh and reconcile evidence before triage.",
            "action_executed": False,
        }

    findings = []
    for service in request.services:
        conditions = []
        severity = "healthy"
        if not service.dependencies_healthy:
            severity, conditions = "critical", ["dependency_unhealthy"]
        if service.error_rate_percent >= 5:
            severity, conditions = "critical", conditions + ["error_rate_critical"]
        elif service.error_rate_percent >= 1:
            severity, conditions = max(severity, "warning", key=_SEVERITY_RANK.get), conditions + ["error_rate_warning"]
        if service.p95_latency_ms >= 2000:
            severity, conditions = "critical", conditions + ["latency_critical"]
        elif service.p95_latency_ms >= 750:
            severity, conditions = max(severity, "warning", key=_SEVERITY_RANK.get), conditions + ["latency_warning"]
        if service.capacity_used_percent >= 90:
            severity, conditions = "critical", conditions + ["capacity_critical"]
        elif service.capacity_used_percent >= 75:
            severity, conditions = max(severity, "warning", key=_SEVERITY_RANK.get), conditions + ["capacity_warning"]
        findings.append({"type": "service", "entity": service.name, "severity": severity,
                         "conditions": conditions, "metrics": service.model_dump()})
    for queue in request.queues:
        severity = "critical" if queue.backlog >= 1000 or queue.oldest_age_seconds >= 600 else (
            "warning" if queue.backlog >= 250 or queue.oldest_age_seconds >= 120 else "healthy"
        )
        findings.append({"type": "queue", "entity": queue.name, "severity": severity,
                         "conditions": ["backlog_or_age_threshold"] if severity != "healthy" else [],
                         "metrics": queue.model_dump()})
    for worker in request.workers:
        severity = "critical" if worker.available_workers == 0 or worker.heartbeat_age_seconds >= 120 else (
            "warning" if worker.heartbeat_age_seconds >= 60 else "healthy"
        )
        findings.append({"type": "worker", "entity": worker.name, "severity": severity,
                         "conditions": ["availability_or_heartbeat_threshold"] if severity != "healthy" else [],
                         "metrics": worker.model_dump()})

    severity = max((item["severity"] for item in findings), key=_SEVERITY_RANK.get)
    material = json.dumps(
        [(item["type"], item["entity"], item["conditions"]) for item in findings if item["conditions"]],
        sort_keys=True,
    )
    incident_key = hashlib.sha256(f"{request.tenant_id}:{material}".encode()).hexdigest()[:24]
    return {
        "tenant_id": request.tenant_id, "status": "ready", "severity": severity,
        "confidence": "high", "observed_at": request.observed_at.isoformat(),
        "analyzed_at": analyzed_at, "evidence_refs": request.evidence_refs,
        "owner": request.owner, "incident_key": incident_key,
        "deduplication_key": incident_key, "findings": findings,
        "similar_incident_ids": request.similar_incident_ids,
        "runbook": {"path": "docs/runbooks/master-runbook.md", "section": "19"},
        "recommended_next_action": (
            "Escalate to the incident owner and follow the cited runbook."
            if severity == "critical" else
            "Inspect warning findings and capacity trends." if severity == "warning" else
            "Continue monitoring."
        ),
        "limitations": ["Analysis is deterministic and limited to submitted evidence."],
        "action_executed": False,
    }
