from datetime import UTC, datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field, model_validator


class DomainSummary(BaseModel):
    domain: Literal[
        "operations", "market_risk", "treasury", "aml_fraud", "security",
        "support", "knowledge", "governance",
    ]
    status: Literal["ready", "blocked", "degraded"]
    severity: Literal["healthy", "normal", "low", "medium", "warning", "high", "critical", "unknown"]
    observed_at: AwareDatetime
    evidence_refs: list[str] = Field(min_length=1, max_length=100)
    owner: str = Field(min_length=2, max_length=100)
    headline: str = Field(min_length=3, max_length=500)
    metrics: dict = Field(default_factory=dict)
    recommended_next_action: str = Field(min_length=3, max_length=500)


class ExecutiveBriefRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=100)
    reporting_period: str = Field(min_length=3, max_length=100)
    freshness_limit_seconds: int = Field(default=300, ge=1, le=604800)
    domains: list[DomainSummary] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def require_unique_domains(self):
        names = [item.domain for item in self.domains]
        if len(names) != len(set(names)):
            raise ValueError("domains must be unique")
        return self


REQUIRED_DOMAINS = {
    "operations", "market_risk", "treasury", "aml_fraud", "security", "support",
}
SEVERITY_RANK = {
    "healthy": 0, "normal": 0, "low": 1, "medium": 2, "warning": 2,
    "high": 3, "critical": 4, "unknown": 5,
}


def build_executive_brief(request: ExecutiveBriefRequest) -> dict:
    now = datetime.now(UTC)
    supplied = {item.domain for item in request.domains}
    missing = sorted(REQUIRED_DOMAINS - supplied)
    stale = []
    blocked = []
    priorities = []
    evidence_refs = []
    for item in request.domains:
        age_seconds = max(0, int((now - item.observed_at.astimezone(UTC)).total_seconds()))
        if age_seconds > request.freshness_limit_seconds:
            stale.append(item.domain)
        if item.status != "ready" or item.severity == "unknown":
            blocked.append(item.domain)
        evidence_refs.extend(item.evidence_refs)
        if SEVERITY_RANK[item.severity] >= 2:
            priorities.append({
                "domain": item.domain, "severity": item.severity, "owner": item.owner,
                "headline": item.headline,
                "recommended_next_action": item.recommended_next_action,
                "evidence_refs": item.evidence_refs,
            })
    priorities.sort(key=lambda item: SEVERITY_RANK[item["severity"]], reverse=True)
    ready = not missing and not stale and not blocked
    overall = (
        "unknown" if not ready else
        max((item.severity for item in request.domains), key=SEVERITY_RANK.get)
    )
    domain_sections = {
        item.domain: {
            "status": item.status, "severity": item.severity,
            "observed_at": item.observed_at.isoformat(), "owner": item.owner,
            "headline": item.headline, "metrics": item.metrics,
            "evidence_refs": item.evidence_refs,
        }
        for item in request.domains
    }
    return {
        "tenant_id": request.tenant_id, "reporting_period": request.reporting_period,
        "generated_at": now.isoformat(), "status": "ready" if ready else "blocked",
        "overall_severity": overall, "confidence": "high" if ready else "none",
        "headline": (
            f"Cross-domain exchange intelligence is {overall}." if ready else
            "Cross-domain brief blocked by incomplete or stale domain evidence."
        ),
        "priorities": priorities if ready else [], "domains": domain_sections,
        "evidence_refs": sorted(set(evidence_refs)),
        "coverage": {
            "required_domains": sorted(REQUIRED_DOMAINS), "missing_domains": missing,
            "stale_domains": sorted(stale), "blocked_domains": sorted(blocked),
            "complete": ready,
        },
        "limitations": (
            [] if ready else ["No executive conclusion is emitted until all required domains are fresh and ready."]
        ),
        "recommended_next_action": (
            priorities[0]["recommended_next_action"] if ready and priorities else
            "Continue scheduled monitoring." if ready else
            "Resolve missing, stale, or blocked domain evidence."
        ),
        "statement": "No action executed by bitAgent.", "action_executed": False,
    }
