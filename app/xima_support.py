import hashlib
import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import AwareDatetime, BaseModel, Field, model_validator


class KnowledgeDocumentRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=100)
    document_id: str = Field(min_length=3, max_length=100)
    title: str = Field(min_length=3, max_length=200)
    document_type: Literal["policy", "runbook", "api", "schema", "incident", "product"]
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    owner: str = Field(min_length=2, max_length=100)
    approval_status: Literal["draft", "approved", "rejected", "superseded"]
    approved_by_role: str | None = Field(default=None, max_length=100)
    effective_at: AwareDatetime
    expires_at: AwareDatetime
    data_class: Literal["public", "internal", "confidential"]
    allowed_roles: list[Literal["viewer", "operator", "auditor", "admin"]] = Field(
        min_length=1, max_length=4
    )
    keywords: list[str] = Field(min_length=1, max_length=100)
    content: str = Field(min_length=20, max_length=100000)
    source_ref: str = Field(min_length=3, max_length=500)

    @model_validator(mode="after")
    def validate_governance(self):
        if self.expires_at <= self.effective_at:
            raise ValueError("expires_at must be after effective_at")
        if self.approval_status == "approved" and not self.approved_by_role:
            raise ValueError("approved documents require approved_by_role")
        return self


class SupportTicketRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=100)
    ticket_id: str = Field(min_length=3, max_length=100)
    observed_at: AwareDatetime
    evidence_refs: list[str] = Field(min_length=1, max_length=100)
    owner: str = Field(min_length=2, max_length=100)
    evidence_fresh: bool
    conflicting_fields: list[str] = Field(default_factory=list, max_length=100)
    language: str = Field(default="en", min_length=2, max_length=12)
    subject: str = Field(min_length=2, max_length=500)
    message: str = Field(min_length=2, max_length=10000)
    account_state: Literal["normal", "restricted", "under_review", "unknown"]


def _connect(path: str) -> sqlite3.Connection:
    database = Path(path)
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS xima_knowledge (
            id INTEGER PRIMARY KEY AUTOINCREMENT, receipt_id TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL, tenant_id TEXT NOT NULL, document_id TEXT NOT NULL,
            title TEXT NOT NULL, document_type TEXT NOT NULL, version TEXT NOT NULL,
            owner TEXT NOT NULL, approval_status TEXT NOT NULL, approved_by_role TEXT,
            effective_at TEXT NOT NULL, expires_at TEXT NOT NULL, data_class TEXT NOT NULL,
            allowed_roles_json TEXT NOT NULL, keywords_json TEXT NOT NULL,
            content TEXT NOT NULL, source_ref TEXT NOT NULL, content_hash TEXT NOT NULL,
            previous_hash TEXT NOT NULL, record_hash TEXT NOT NULL UNIQUE,
            UNIQUE(tenant_id, document_id, version)
        )
        """
    )
    return connection


def ingest_knowledge(path: str, request: KnowledgeDocumentRequest) -> tuple[int, dict]:
    receipt_id = str(uuid4())
    created_at = datetime.now(UTC).isoformat()
    content_hash = hashlib.sha256(request.content.encode()).hexdigest()
    with _connect(path) as connection:
        previous = connection.execute(
            "SELECT record_hash FROM xima_knowledge ORDER BY id DESC LIMIT 1"
        ).fetchone()
        previous_hash = previous["record_hash"] if previous else "0" * 64
        material = json.dumps(request.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        record_hash = hashlib.sha256(
            f"{previous_hash}\n{created_at}\n{receipt_id}\n{material}".encode()
        ).hexdigest()
        try:
            cursor = connection.execute(
                "INSERT INTO xima_knowledge "
                "(receipt_id,created_at,tenant_id,document_id,title,document_type,version,owner,"
                "approval_status,approved_by_role,effective_at,expires_at,data_class,"
                "allowed_roles_json,keywords_json,content,source_ref,content_hash,previous_hash,record_hash) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (receipt_id, created_at, request.tenant_id, request.document_id, request.title,
                 request.document_type, request.version, request.owner, request.approval_status,
                 request.approved_by_role, request.effective_at.isoformat(),
                 request.expires_at.isoformat(), request.data_class,
                 json.dumps(request.allowed_roles), json.dumps(request.keywords), request.content,
                 request.source_ref, content_hash, previous_hash, record_hash),
            )
        except sqlite3.IntegrityError:
            return 409, {"code": "knowledge_version_exists"}
    return 201, {
        "id": cursor.lastrowid, "receipt_id": receipt_id, "tenant_id": request.tenant_id,
        "document_id": request.document_id, "version": request.version,
        "approval_status": request.approval_status, "content_hash": content_hash,
        "record_hash": record_hash, "created_at": created_at,
        "exchange_write_performed": False,
    }


def _terms(value: str) -> set[str]:
    return {term for term in re.findall(r"[a-z0-9]{3,}", value.lower())}


def retrieve_knowledge(path: str, tenant_id: str, role: str, query: str, limit: int = 5) -> list[dict]:
    now = datetime.now(UTC)
    with _connect(path) as connection:
        rows = connection.execute(
            "SELECT * FROM xima_knowledge WHERE tenant_id=? AND approval_status='approved' "
            "ORDER BY id DESC", (tenant_id,),
        ).fetchall()
    query_terms = _terms(query)
    results = []
    seen_documents = set()
    for row in rows:
        if row["document_id"] in seen_documents:
            continue
        effective = datetime.fromisoformat(row["effective_at"])
        expires = datetime.fromisoformat(row["expires_at"])
        allowed_roles = json.loads(row["allowed_roles_json"])
        if not (effective <= now < expires) or role not in allowed_roles:
            continue
        searchable = _terms(f"{row['title']} {' '.join(json.loads(row['keywords_json']))} {row['content']}")
        score = len(query_terms & searchable)
        if not score:
            continue
        seen_documents.add(row["document_id"])
        results.append({
            "document_id": row["document_id"], "title": row["title"],
            "version": row["version"], "owner": row["owner"],
            "source_ref": row["source_ref"], "content_hash": row["content_hash"],
            "expires_at": row["expires_at"], "score": score,
            "excerpt": row["content"][:500],
        })
    return sorted(results, key=lambda item: item["score"], reverse=True)[:limit]


def _redact(value: str) -> str:
    value = re.sub(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", "[REDACTED_EMAIL]", value,
                   flags=re.IGNORECASE)
    value = re.sub(r"\b\d{8,19}\b", "[REDACTED_NUMBER]", value)
    return value


def analyze_support(path: str, request: SupportTicketRequest, role: str) -> dict:
    now = datetime.now(UTC).isoformat()
    common = {
        "tenant_id": request.tenant_id, "ticket_id": request.ticket_id,
        "observed_at": request.observed_at.isoformat(), "analyzed_at": now,
        "evidence_refs": request.evidence_refs, "owner": request.owner,
        "action_executed": False,
    }
    if not request.evidence_fresh or request.conflicting_fields:
        return {
            **common, "status": "blocked", "confidence": "none", "severity": "unknown",
            "classification": None, "draft": None, "citations": [],
            "limitations": ["Ticket evidence is stale or conflicting."],
            "recommended_next_action": "Refresh ticket and account-state evidence.",
        }
    text = f"{request.subject} {request.message}".lower()
    intent_rules = (
        ("account_security", ("hacked", "unauthorized", "phishing", "password")),
        ("withdrawal", ("withdraw", "withdrawal")),
        ("deposit", ("deposit",)),
        ("verification", ("verify", "verification", "kyc")),
        ("trading", ("order", "trade", "price")),
    )
    intent = next((name for name, terms in intent_rules if any(term in text for term in terms)), "general")
    dissatisfaction = any(term in text for term in ("angry", "terrible", "unacceptable", "complaint", "lawsuit"))
    urgent = any(term in text for term in ("urgent", "immediately", "hacked", "unauthorized", "missing funds"))
    sensitive = intent == "account_security" or request.account_state in {"restricted", "under_review", "unknown"}
    escalate = urgent or dissatisfaction or sensitive
    citations = retrieve_knowledge(path, request.tenant_id, role, text)
    safe_subject = _redact(request.subject)
    safe_message = _redact(request.message)
    draft = None
    if citations:
        draft = (
            f"We understand your {intent.replace('_', ' ')} question. "
            f"Based on the approved guidance '{citations[0]['title']}', please follow the cited steps. "
            "Never share a password, private key, seed phrase, or authentication code. "
            "A human specialist will review any account-specific decision."
        )
    return {
        **common, "status": "ready", "confidence": "high" if citations else "limited",
        "severity": "high" if escalate else "normal",
        "classification": {"intent": intent, "urgent": urgent,
                           "dissatisfaction": dissatisfaction, "escalate": escalate},
        "redacted_ticket": {"subject": safe_subject, "message": safe_message},
        "draft": draft, "citations": citations,
        "human_review_required": True, "send_enabled": False,
        "limitations": (["No approved matching knowledge was found."] if not citations else []),
        "recommended_next_action": (
            "Escalate to an authorized specialist." if escalate else
            "Review the cited draft before any response."
        ),
    }
