import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from pydantic import AwareDatetime, BaseModel, Field, ValidationError

from app.xima_shadow import ShadowPilotRequest, evaluate_shadow_pilot


class ExchangeRouteEvidence(BaseModel):
    path: str = Field(min_length=2, max_length=300)
    passed: bool
    evidence_ref: str = Field(min_length=3, max_length=500)


class ExchangePilotEvidence(BaseModel):
    contract_version: str = Field(min_length=1, max_length=50)
    approved_by: str = Field(min_length=2, max_length=100)
    approved_at: AwareDatetime
    authentication_passed: bool
    freshness_sla_approved: bool
    routes: list[ExchangeRouteEvidence] = Field(min_length=1, max_length=100)


class UpstreamSourceEvidence(BaseModel):
    approved_by: str = Field(min_length=2, max_length=100)
    approved_at: AwareDatetime
    freshness_sla_approved: bool
    live_paths: list[str] = Field(min_length=1, max_length=100)


class KnowledgePilotEvidence(BaseModel):
    approved_by: str = Field(min_length=2, max_length=100)
    approved_at: AwareDatetime
    owner_reviewed: bool
    privacy_retention_approved: bool
    document_ids: list[str] = Field(min_length=1, max_length=10000)


class SteeringApproval(BaseModel):
    approved_at: AwareDatetime
    approved_by: list[str] = Field(min_length=2, max_length=20)
    read_only_pilot_approved: bool
    controlled_actions_approved: bool = False


class PilotEvidencePackage(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=100)
    exchange: ExchangePilotEvidence
    upstream_sources: UpstreamSourceEvidence
    knowledge: KnowledgePilotEvidence
    shadow_pilot: ShadowPilotRequest
    steering: SteeringApproval


def load_pilot_evidence(directory: str) -> dict:
    path = Path(directory) / "pilot.local.json"
    if not path.exists():
        return {"status": "missing", "path": str(path), "contains_credentials": False}
    try:
        raw = path.read_bytes()
        package = PilotEvidencePackage.model_validate_json(raw)
    except (OSError, ValidationError, ValueError) as exc:
        return {
            "status": "invalid", "path": str(path),
            "error": "validation_failed", "error_type": type(exc).__name__,
            "contains_credentials": False,
        }
    return {
        "status": "valid", "path": str(path),
        "sha256": hashlib.sha256(raw).hexdigest(), "package": package,
        "contains_credentials": False,
    }


def build_pilot_manifest(
    *,
    current_version: str,
    tenant_id: str,
    identity: dict,
    access_reviews: list[dict],
    audit: dict,
    knowledge_items: list[dict],
    delivery: dict,
    pilot_evidence: dict,
    exchange_paths: set[str],
    upstream_paths: set[str],
) -> dict:
    now = datetime.now(UTC)
    latest_review = access_reviews[0] if access_reviews else None
    access_review_passed = bool(
        latest_review
        and latest_review.get("approved")
        and latest_review.get("exception_count") == 0
        and datetime.fromisoformat(latest_review["next_review_at"]) > now
    )
    approved_knowledge = [
        item for item in knowledge_items
        if item.get("status") == "approved" and item.get("lifecycle") == "active"
    ]
    audit_passed = bool(
        audit.get("evidence", {}).get("valid")
        and audit.get("xima_outputs", {}).get("valid")
    )

    package = pilot_evidence.get("package")
    if isinstance(package, PilotEvidencePackage) and package.tenant_id == tenant_id:
        evidence_dates_valid = all(date <= now for date in (
            package.exchange.approved_at, package.upstream_sources.approved_at,
            package.knowledge.approved_at, package.steering.approved_at,
            package.shadow_pilot.window_end,
        )) and package.shadow_pilot.window_start < package.shadow_pilot.window_end
        exchange_evidence_paths = {item.path for item in package.exchange.routes if item.passed}
        exchange_passed = bool(
            evidence_dates_valid
            and package.exchange.contract_version == "0.8.0-pilot"
            and package.exchange.authentication_passed
            and package.exchange.freshness_sla_approved
            and exchange_evidence_paths == exchange_paths
        )
        live_paths = set(package.upstream_sources.live_paths)
        upstream_passed = bool(
            evidence_dates_valid
            and package.upstream_sources.freshness_sla_approved
            and live_paths == upstream_paths
        )
        approved_document_ids = {item.get("document_id") for item in approved_knowledge}
        knowledge_passed = bool(
            evidence_dates_valid
            and package.knowledge.owner_reviewed
            and package.knowledge.privacy_retention_approved
            and set(package.knowledge.document_ids).issubset(approved_document_ids)
        )
        shadow = evaluate_shadow_pilot(package.shadow_pilot)
        tenant_matched = package.shadow_pilot.tenant_id == tenant_id
        shadow_passed = evidence_dates_valid and tenant_matched and shadow["status"] == "ready"
        steering_passed = bool(
            evidence_dates_valid
            and package.steering.read_only_pilot_approved
            and len(package.steering.approved_by) >= 2
            and len(set(package.steering.approved_by)) == len(package.steering.approved_by)
        )
        controlled_actions = package.steering.controlled_actions_approved
    else:
        exchange_passed = upstream_passed = knowledge_passed = False
        shadow_passed = steering_passed = False
        controlled_actions = False
        shadow = None

    checks = [
        ("production-identity", identity.get("status") == "ready",
         "OIDC, MFA, role, tenant and enforced RBAC configured"),
        ("current-access-review", access_review_passed,
         "approved zero-exception review remains in force"),
        ("audit-integrity", audit_passed,
         "evidence and XIMA output chains verify"),
        ("governed-knowledge", knowledge_passed,
         f"{len(approved_knowledge)} active document(s); owner and privacy/retention evidence required"),
        ("secure-delivery", bool(delivery.get("ready")),
         "signed webhook configured and tenant subscription exists"),
        ("exchange-api-contract", exchange_passed,
         f"all {len(exchange_paths)} OpenAPI routes require passing owner evidence"),
        ("upstream-domain-sources", upstream_passed,
         f"all {len(upstream_paths)} minimized source contracts require live evidence"),
        ("shadow-and-reliability", shadow_passed,
         "outcomes, reports, load, soak, failover, restore, monitoring, runbooks, training and eight owner roles pass"),
        ("steering-read-only-approval", steering_passed,
         "two or more steering approvers explicitly approve the read-only pilot"),
    ]
    gates = [
        {"id": gate_id, "status": "pass" if passed else "pending", "evidence": evidence}
        for gate_id, passed, evidence in checks
    ]
    blockers = [gate for gate in gates if gate["status"] != "pass"]
    approved = not blockers
    receipt_material = {
        "candidate_version": "3.0.0-rc.1", "current_version": current_version,
        "tenant_id": tenant_id, "gates": gates,
        "external_evidence_sha256": pilot_evidence.get("sha256"),
    }
    receipt = hashlib.sha256(json.dumps(
        receipt_material, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()
    return {
        "candidate_version": "3.0.0-rc.1", "current_version": current_version,
        "tenant_id": tenant_id, "generated_at": now.isoformat(),
        "decision": "eligible_for_read_only_pilot_review" if approved else "blocked",
        "approved": approved, "passed": len(gates) - len(blockers),
        "total": len(gates), "gates": gates, "blockers": blockers,
        "shadow_evaluation": shadow,
        "external_evidence": {
            key: value for key, value in pilot_evidence.items() if key != "package"
        },
        "evidence_sha256": receipt,
        "controlled_actions_enabled": False,
        "controlled_action_approval_observed": controlled_actions,
        "external_approval_still_required": not approved,
        "secrets_exposed": False, "action_executed": False,
    }
