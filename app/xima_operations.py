import hashlib
import json
from datetime import UTC, datetime

from pydantic import AwareDatetime, BaseModel, Field


class ServiceMetric(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    error_rate_percent: float = Field(ge=0, le=100)
    p95_latency_ms: int = Field(ge=0, le=3_600_000)
    capacity_used_percent: float = Field(ge=0, le=100)
    dependencies_healthy: bool
    request_rate_per_second: float | None = Field(default=None, ge=0)
    p99_latency_ms: int | None = Field(default=None, ge=0, le=3_600_000)


class QueueMetric(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    backlog: int = Field(ge=0)
    oldest_age_seconds: int = Field(ge=0)
    throughput_per_minute: float = Field(ge=0)
    enqueue_rate_per_minute: float | None = Field(default=None, ge=0)
    failure_rate_percent: float = Field(default=0, ge=0, le=100)
    retry_count: int = Field(default=0, ge=0)
    dead_letter_count: int = Field(default=0, ge=0)
    consumer_count: int | None = Field(default=None, ge=0)
    capacity_used_percent: float | None = Field(default=None, ge=0, le=100)


class WorkerMetric(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    heartbeat_age_seconds: int = Field(ge=0)
    available_workers: int = Field(ge=0)
    desired_workers: int | None = Field(default=None, ge=0)
    busy_workers: int | None = Field(default=None, ge=0)
    unhealthy_workers: int = Field(default=0, ge=0)
    restart_count: int = Field(default=0, ge=0)
    throughput_per_minute: float | None = Field(default=None, ge=0)


class DependencyMetric(BaseModel):
    source: str = Field(min_length=1, max_length=100)
    target: str = Field(min_length=1, max_length=100)
    state: str = Field(pattern=r"^(healthy|degraded|unavailable|maintenance|unknown)$")
    criticality: str = Field(pattern=r"^(low|medium|high|critical)$")
    failure_impact: str = Field(min_length=3, max_length=500)
    last_transition_at: AwareDatetime | None = None
    owner: str = Field(min_length=2, max_length=100)
    runbook_id: str | None = Field(default=None, max_length=100)


class NetworkMetric(BaseModel):
    network: str = Field(min_length=1, max_length=50)
    deposits_enabled: bool
    withdrawals_enabled: bool
    sync_lag_blocks: int = Field(ge=0)
    peer_count: int = Field(ge=0)
    confirmation_target: int = Field(ge=0)
    observed_confirmation_seconds: int | None = Field(default=None, ge=0)
    wallet_connected: bool
    maintenance: bool = False
    reason: str | None = Field(default=None, max_length=500)


class OperationsAnalysisRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=100)
    observed_at: AwareDatetime
    evidence_refs: list[str] = Field(min_length=1, max_length=100)
    owner: str = Field(min_length=2, max_length=100)
    evidence_fresh: bool
    conflicting_fields: list[str] = Field(default_factory=list, max_length=100)
    services: list[ServiceMetric] = Field(min_length=1, max_length=100)
    queues: list[QueueMetric] = Field(default_factory=list, max_length=100)
    workers: list[WorkerMetric] = Field(default_factory=list, max_length=100)
    dependencies: list[DependencyMetric] = Field(default_factory=list, max_length=500)
    networks: list[NetworkMetric] = Field(default_factory=list, max_length=100)
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
        severity = "critical" if (queue.backlog >= 1000 or queue.oldest_age_seconds >= 600
                                  or queue.dead_letter_count >= 100 or queue.failure_rate_percent >= 5) else (
            "warning" if queue.backlog >= 250 or queue.oldest_age_seconds >= 120 else "healthy"
        )
        conditions = []
        if severity != "healthy": conditions.append("backlog_or_age_threshold")
        if queue.enqueue_rate_per_minute is not None and queue.enqueue_rate_per_minute > queue.throughput_per_minute:
            conditions.append("arrival_rate_exceeds_throughput")
        if queue.dead_letter_count: conditions.append("dead_letters_present")
        if queue.failure_rate_percent >= 1: conditions.append("queue_failures_elevated")
        findings.append({"type": "queue", "entity": queue.name, "severity": severity,
                         "conditions": conditions,
                         "metrics": queue.model_dump()})
    for worker in request.workers:
        severity = "critical" if worker.available_workers == 0 or worker.heartbeat_age_seconds >= 120 else (
            "warning" if worker.heartbeat_age_seconds >= 60 else "healthy"
        )
        findings.append({"type": "worker", "entity": worker.name, "severity": severity,
                         "conditions": ["availability_or_heartbeat_threshold"] if severity != "healthy" else [],
                         "metrics": worker.model_dump()})
    for dependency in request.dependencies:
        severity = "critical" if dependency.state == "unavailable" and dependency.criticality in {"high", "critical"} else (
            "warning" if dependency.state != "healthy" else "healthy"
        )
        findings.append({"type": "dependency", "entity": f"{dependency.source}->{dependency.target}",
                         "severity": severity,
                         "conditions": [f"dependency_{dependency.state}"] if severity != "healthy" else [],
                         "metrics": dependency.model_dump(mode="json")})
    for network in request.networks:
        disabled = not network.deposits_enabled or not network.withdrawals_enabled
        severity = "critical" if (not network.wallet_connected or network.sync_lag_blocks >= 20) else (
            "warning" if disabled or network.maintenance or network.sync_lag_blocks >= 5 else "healthy"
        )
        conditions = []
        if not network.wallet_connected: conditions.append("wallet_disconnected")
        if network.sync_lag_blocks >= 5: conditions.append("node_sync_lag")
        if disabled: conditions.append("deposit_or_withdrawal_disabled")
        if network.maintenance: conditions.append("network_maintenance")
        findings.append({"type": "network", "entity": network.network, "severity": severity,
                         "conditions": conditions, "metrics": network.model_dump()})

    severity = max((item["severity"] for item in findings), key=_SEVERITY_RANK.get)
    material = json.dumps(
        [(item["type"], item["entity"], item["conditions"]) for item in findings if item["conditions"]],
        sort_keys=True,
    )
    incident_key = hashlib.sha256(f"{request.tenant_id}:{material}".encode()).hexdigest()[:24]
    hypotheses = []
    for dependency in request.dependencies:
        if dependency.state != "healthy":
            hypotheses.append({"candidate": dependency.target,
                               "kind": "upstream_dependency",
                               "state": dependency.state,
                               "impact": dependency.failure_impact,
                               "affected_service": dependency.source,
                               "owner": dependency.owner,
                               "runbook_id": dependency.runbook_id,
                               "confidence": "high" if dependency.state == "unavailable" else "medium",
                               "causality": "hypothesis"})
    for worker in request.workers:
        if worker.available_workers == 0 or worker.heartbeat_age_seconds >= 120:
            hypotheses.append({"candidate": worker.name, "kind": "worker_pool",
                               "state": "unavailable" if worker.available_workers == 0 else "stale",
                               "impact": "Queue processing capacity may be unavailable.",
                               "confidence": "medium", "causality": "hypothesis"})
    for queue in request.queues:
        if (queue.enqueue_rate_per_minute is not None
                and queue.enqueue_rate_per_minute > queue.throughput_per_minute):
            hypotheses.append({"candidate": queue.name, "kind": "queue_capacity",
                               "state": "inflow_exceeds_outflow",
                               "impact": "Backlog will grow while the rate imbalance persists.",
                               "confidence": "high", "causality": "observed_condition"})
    priority = {"unavailable": 0, "inflow_exceeds_outflow": 1, "degraded": 2, "stale": 3}
    hypotheses.sort(key=lambda item: priority.get(item["state"], 9))
    return {
        "tenant_id": request.tenant_id, "status": "ready", "severity": severity,
        "confidence": "high", "observed_at": request.observed_at.isoformat(),
        "analyzed_at": analyzed_at, "evidence_refs": request.evidence_refs,
        "owner": request.owner, "incident_key": incident_key,
        "deduplication_key": incident_key, "findings": findings,
        "similar_incident_ids": request.similar_incident_ids,
        "root_cause_analysis": {
            "status": "hypotheses_available" if hypotheses else "no_candidate",
            "candidates": hypotheses,
            "confirmed_root_cause": None,
            "confirmation_required": bool(hypotheses),
        },
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
