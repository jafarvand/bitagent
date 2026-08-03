import hashlib
import json
import sqlite3
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import jwt
from pydantic import AwareDatetime, BaseModel, Field


identity_context: ContextVar[dict | None] = ContextVar("identity_context", default=None)


class AccessReviewRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=100)
    reviewed_at: AwareDatetime
    reviewer: str = Field(min_length=2, max_length=100)
    subject_count: int = Field(ge=0)
    exception_count: int = Field(ge=0)
    approved: bool
    evidence_ref: str = Field(min_length=3, max_length=500)
    next_review_at: AwareDatetime


def identity_readiness(settings) -> dict:
    gates = {
        "oidc_mode": settings.bitagent_identity_mode == "oidc",
        "issuer": bool(settings.bitagent_oidc_issuer),
        "audience": bool(settings.bitagent_oidc_audience),
        "verification_key": bool(settings.bitagent_oidc_jwks_url
                                 or settings.bitagent_oidc_public_key.get_secret_value()),
        "mfa_required": settings.bitagent_oidc_require_mfa,
        "tenant_claim": bool(settings.bitagent_oidc_tenant_claim),
        "role_claim": bool(settings.bitagent_oidc_role_claim),
        "access_review_reference": bool(settings.bitagent_access_review_ref),
        "enforced_rbac": settings.bitagent_access_control_mode == "enforced",
    }
    return {"status": "ready" if all(gates.values()) else "blocked", "gates": gates,
            "missing": [name for name, passed in gates.items() if not passed],
            "accepted_algorithms": ["RS256", "ES256"],
            "pilot_header_allowed": settings.bitagent_identity_mode == "pilot_header",
            "secrets_exposed": False}


def verify_oidc_token(token: str, settings) -> dict:
    key = settings.bitagent_oidc_public_key.get_secret_value()
    if key:
        verification_key = key
    elif settings.bitagent_oidc_jwks_url:
        verification_key = jwt.PyJWKClient(settings.bitagent_oidc_jwks_url).get_signing_key_from_jwt(token).key
    else:
        raise ValueError("OIDC verification key is not configured")
    claims = jwt.decode(token, verification_key, algorithms=["RS256", "ES256"],
                        audience=settings.bitagent_oidc_audience,
                        issuer=settings.bitagent_oidc_issuer,
                        options={"require": ["exp", "iat", "sub", "iss", "aud"]})
    role = claims.get(settings.bitagent_oidc_role_claim)
    tenant_id = claims.get(settings.bitagent_oidc_tenant_claim)
    if role not in {"viewer", "operator", "auditor", "admin"}:
        raise ValueError("OIDC role claim is missing or invalid")
    if not isinstance(tenant_id, str) or not tenant_id:
        raise ValueError("OIDC tenant claim is missing or invalid")
    amr = claims.get("amr", [])
    mfa = claims.get("mfa") is True or (isinstance(amr, list)
                                        and bool({"mfa", "otp", "hwk"} & set(amr)))
    if settings.bitagent_oidc_require_mfa and not mfa:
        raise ValueError("MFA evidence is required")
    return {"role": role, "tenant_id": tenant_id, "mfa": mfa,
            "subject_hash": hashlib.sha256(claims["sub"].encode()).hexdigest(),
            "issuer": claims["iss"], "expires_at": datetime.fromtimestamp(claims["exp"], UTC).isoformat()}


def _connect(path: str) -> sqlite3.Connection:
    database = Path(path); database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database); connection.row_factory = sqlite3.Row
    connection.execute("""
        CREATE TABLE IF NOT EXISTS identity_access_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT, review_id TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL, tenant_id TEXT NOT NULL, reviewed_at TEXT NOT NULL,
            reviewer TEXT NOT NULL, subject_count INTEGER NOT NULL, exception_count INTEGER NOT NULL,
            approved INTEGER NOT NULL, evidence_ref TEXT NOT NULL, next_review_at TEXT NOT NULL,
            previous_hash TEXT NOT NULL, record_hash TEXT NOT NULL UNIQUE)
    """)
    return connection


def record_access_review(path: str, request: AccessReviewRequest) -> dict:
    if request.next_review_at <= request.reviewed_at:
        raise ValueError("next_review_at must be after reviewed_at")
    review_id, created_at = str(uuid4()), datetime.now(UTC).isoformat()
    with _connect(path) as connection:
        previous = connection.execute(
            "SELECT record_hash FROM identity_access_reviews ORDER BY id DESC LIMIT 1"
        ).fetchone()
        previous_hash = previous["record_hash"] if previous else "0" * 64
        material = json.dumps(request.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        record_hash = hashlib.sha256(
            f"{previous_hash}\n{review_id}\n{created_at}\n{material}".encode()).hexdigest()
        cursor = connection.execute(
            "INSERT INTO identity_access_reviews "
            "(review_id,created_at,tenant_id,reviewed_at,reviewer,subject_count,exception_count,approved,evidence_ref,next_review_at,previous_hash,record_hash) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (review_id, created_at, request.tenant_id, request.reviewed_at.isoformat(),
             request.reviewer, request.subject_count, request.exception_count, int(request.approved),
             request.evidence_ref, request.next_review_at.isoformat(), previous_hash, record_hash))
    return {"id": cursor.lastrowid, "review_id": review_id, "created_at": created_at,
            "tenant_id": request.tenant_id, "approved": request.approved,
            "exception_count": request.exception_count, "record_hash": record_hash}


def recent_access_reviews(path: str, tenant_id: str, limit: int = 20) -> list[dict]:
    with _connect(path) as connection:
        rows = connection.execute(
            "SELECT review_id,created_at,tenant_id,reviewed_at,reviewer,subject_count,exception_count,approved,evidence_ref,next_review_at,record_hash "
            "FROM identity_access_reviews WHERE tenant_id=? ORDER BY id DESC LIMIT ?",
            (tenant_id, limit)).fetchall()
    return [{**dict(row), "approved": bool(row["approved"])} for row in rows]
