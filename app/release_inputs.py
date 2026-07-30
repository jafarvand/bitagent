import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from app.incidents import detect_withdrawal_slowdown


class HistoricalIncident(BaseModel):
    incident_id: str = Field(min_length=1, max_length=200)
    owner: str = Field(min_length=1, max_length=200)
    approved_at: str = Field(min_length=10, max_length=40)
    pending_withdrawals: int = Field(ge=0)
    withdrawals: int = Field(ge=0)
    expected_severity: Literal["healthy", "notice", "warning", "critical"]


class IncidentPackage(BaseModel):
    incidents: list[HistoricalIncident] = Field(min_length=5, max_length=20)


class ExternalSecurityEvidence(BaseModel):
    approved_by: str = Field(min_length=1, max_length=200)
    approved_at: str = Field(min_length=10, max_length=40)
    non_allowlisted_ip_denied: bool
    wrong_scope_denied: bool
    rotation_tested: bool
    revocation_tested: bool


class IdentityEvidence(BaseModel):
    approved_by: str = Field(min_length=1, max_length=200)
    approved_at: str = Field(min_length=10, max_length=40)
    sso_jwt_enabled: bool
    mfa_required: bool
    access_review_complete: bool


class UATApproval(BaseModel):
    approved_at: str = Field(min_length=10, max_length=40)
    operations_approver: str = Field(min_length=1, max_length=200)
    risk_approver: str = Field(min_length=1, max_length=200)
    operations_approved: bool
    risk_approved: bool


def _load(path: Path, model: type[BaseModel]) -> tuple[BaseModel | None, dict]:
    if not path.exists():
        return None, {"status": "missing", "path": str(path)}
    try:
        raw = path.read_bytes()
        value = model.model_validate_json(raw)
    except (OSError, ValidationError, ValueError) as exc:
        return None, {
            "status": "invalid",
            "path": str(path),
            "error": "validation_failed",
            "error_type": type(exc).__name__,
        }
    return value, {
        "status": "valid",
        "path": str(path),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def validate_release_inputs(
    directory: str,
    *,
    warning_threshold: int,
    critical_threshold: int,
) -> dict:
    root = Path(directory)
    incidents, incident_meta = _load(root / "incidents.local.json", IncidentPackage)
    external_security, security_meta = _load(
        root / "security.local.json", ExternalSecurityEvidence
    )
    identity, identity_meta = _load(root / "identity.local.json", IdentityEvidence)
    approval, approval_meta = _load(root / "uat-approval.local.json", UATApproval)

    incident_cases = []
    if isinstance(incidents, IncidentPackage):
        for item in incidents.incidents:
            result = detect_withdrawal_slowdown(
                {
                    "data": {
                        "pending_withdrawals": item.pending_withdrawals,
                        "withdrawals": item.withdrawals,
                    },
                    "meta": {
                        "request_id": f"owner-{item.incident_id}",
                        "generated_at": item.approved_at,
                        "data_freshness_seconds": 0,
                    },
                },
                warning_threshold=warning_threshold,
                critical_threshold=critical_threshold,
            )
            incident_cases.append(
                {
                    "incident_id": item.incident_id,
                    "expected": item.expected_severity,
                    "actual": result["severity"],
                    "passed": result["severity"] == item.expected_severity,
                }
            )

    incident_pass = bool(incident_cases) and all(
        case["passed"] for case in incident_cases
    )
    security_pass = isinstance(external_security, ExternalSecurityEvidence) and all(
        (
            external_security.non_allowlisted_ip_denied,
            external_security.wrong_scope_denied,
            external_security.rotation_tested,
            external_security.revocation_tested,
        )
    )
    identity_pass = isinstance(identity, IdentityEvidence) and all(
        (identity.sso_jwt_enabled, identity.mfa_required, identity.access_review_complete)
    )
    approval_pass = isinstance(approval, UATApproval) and all(
        (approval.operations_approved, approval.risk_approved)
    )

    return {
        "directory": str(root),
        "owner_incidents": {
            **incident_meta,
            "passed": incident_pass,
            "cases": incident_cases,
        },
        "external_security": {**security_meta, "passed": bool(security_pass)},
        "production_identity": {**identity_meta, "passed": bool(identity_pass)},
        "uat_approval": {**approval_meta, "passed": bool(approval_pass)},
        "all_passed": all(
            (incident_pass, security_pass, identity_pass, approval_pass)
        ),
        "contains_credentials": False,
    }
