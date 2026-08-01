from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field


class SecurityEvent(BaseModel):
    event_id: str = Field(min_length=3, max_length=100)
    category: Literal["authentication", "admin", "iam", "waf", "host", "application"]
    action: str = Field(min_length=2, max_length=100)
    outcome: Literal["success", "failure", "blocked", "unknown"]
    source_severity: Literal["info", "low", "medium", "high", "critical"]
    occurred_at: AwareDatetime
    opaque_actor_id: str = Field(min_length=3, max_length=100)
    target: str = Field(min_length=2, max_length=100)
    source_classification: str = Field(min_length=2, max_length=100)
    correlation_id: str = Field(min_length=3, max_length=100)
    privileged: bool = False
    mfa_present: bool = False
    approved_change_ref: str | None = Field(default=None, max_length=100)
    risk_indicators: list[str] = Field(default_factory=list, max_length=50)


class SecurityAnalysisRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=100)
    observed_at: AwareDatetime
    evidence_refs: list[str] = Field(min_length=1, max_length=100)
    owner: str = Field(min_length=2, max_length=100)
    evidence_fresh: bool
    conflicting_fields: list[str] = Field(default_factory=list, max_length=100)
    events: list[SecurityEvent] = Field(min_length=1, max_length=5000)


def analyze_security(request: SecurityAnalysisRequest) -> dict:
    now = datetime.now(UTC).isoformat()
    common = {
        "tenant_id": request.tenant_id, "observed_at": request.observed_at.isoformat(),
        "analyzed_at": now, "evidence_refs": request.evidence_refs,
        "owner": request.owner, "action_executed": False,
    }
    if not request.evidence_fresh or request.conflicting_fields:
        return {
            **common, "status": "blocked", "severity": "unknown", "confidence": "none",
            "incidents": [], "privileged_activity": [],
            "limitations": (
                (["stale evidence"] if not request.evidence_fresh else []) +
                ([f"conflicting fields: {', '.join(request.conflicting_fields)}"]
                 if request.conflicting_fields else [])
            ),
            "recommended_next_action": "Refresh and reconcile security evidence.",
        }
    grouped = defaultdict(list)
    for event in request.events:
        grouped[event.correlation_id].append(event)
    incidents = []
    severity_rank = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
    for correlation_id, events in grouped.items():
        indicators = sorted({indicator for event in events for indicator in event.risk_indicators})
        failure_count = sum(event.outcome == "failure" for event in events)
        privileged_unapproved = any(
            event.privileged and event.outcome == "success" and not event.approved_change_ref
            for event in events
        )
        privileged_without_mfa = any(event.privileged and not event.mfa_present for event in events)
        categories = sorted({event.category for event in events})
        base = max((event.source_severity for event in events), key=severity_rank.get)
        severity = "critical" if privileged_unapproved or "credential_compromise" in indicators else (
            "high" if privileged_without_mfa or failure_count >= 5 or len(categories) >= 3 else
            base if base in {"high", "medium", "low"} else "low"
        )
        if severity in {"high", "critical"} or indicators or failure_count >= 3:
            actors = sorted({event.opaque_actor_id for event in events})
            incidents.append({
                "correlation_id": correlation_id, "severity": severity,
                "event_ids": [event.event_id for event in events], "categories": categories,
                "opaque_actor_ids": actors, "failure_count": failure_count,
                "risk_indicators": indicators,
                "privileged_unapproved": privileged_unapproved,
                "privileged_without_mfa": privileged_without_mfa,
                "narrative": (
                    f"{len(events)} correlated event(s) across {', '.join(categories)} "
                    f"for {len(actors)} opaque actor(s); human investigation required."
                ),
                "escalate": severity in {"high", "critical"},
            })
    incident_rank = {"low": 1, "medium": 2, "high": 3, "critical": 4}
    incidents.sort(key=lambda item: incident_rank[item["severity"]], reverse=True)
    privileged_activity = [
        {
            "event_id": event.event_id, "opaque_actor_id": event.opaque_actor_id,
            "action": event.action, "target": event.target, "outcome": event.outcome,
            "mfa_present": event.mfa_present,
            "approved_change_ref": event.approved_change_ref,
            "occurred_at": event.occurred_at.isoformat(),
            "review_required": not event.mfa_present or not event.approved_change_ref,
        }
        for event in request.events if event.privileged
    ]
    counts = Counter(event.category for event in request.events)
    severity = incidents[0]["severity"] if incidents else "healthy"
    return {
        **common, "status": "ready", "severity": severity, "confidence": "high",
        "incidents": incidents, "privileged_activity": privileged_activity,
        "daily_brief": {
            "event_count": len(request.events), "events_by_category": dict(sorted(counts.items())),
            "incident_count": len(incidents),
            "critical_count": sum(item["severity"] == "critical" for item in incidents),
            "privileged_review_count": sum(item["review_required"] for item in privileged_activity),
        },
        "limitations": ["Network and actor identifiers are minimized; correlation is deterministic."],
        "recommended_next_action": (
            "Escalate critical correlated activity to the security incident owner."
            if severity == "critical" else
            "Review high-risk correlations and privileged activity." if incidents else
            "Continue monitoring."
        ),
    }
