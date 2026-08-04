import hashlib
import base64
import io
import json
import re
import sqlite3
import unicodedata
import zipfile
from html.parser import HTMLParser
from urllib.request import Request, urlopen
from xml.etree import ElementTree
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import AwareDatetime, BaseModel, Field, model_validator


class KnowledgeDocumentMetadata(BaseModel):
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
    source_ref: str = Field(min_length=3, max_length=500)

    @model_validator(mode="after")
    def validate_governance(self):
        if self.expires_at <= self.effective_at:
            raise ValueError("expires_at must be after effective_at")
        if self.approval_status == "approved" and not self.approved_by_role:
            raise ValueError("approved documents require approved_by_role")
        return self


class KnowledgeDocumentRequest(KnowledgeDocumentMetadata):
    content: str = Field(min_length=20, max_length=100000)


class KnowledgeUploadRequest(BaseModel):
    document: KnowledgeDocumentMetadata
    filename: str = Field(min_length=3, max_length=255)
    content_base64: str = Field(min_length=4, max_length=14_000_000)


BITIMEN_TERMS_URL = "https://bitimen.com/terms/"
BITIMEN_HOW_TO_USE_URL = "https://bitimen.com/how-to-use/"


class BitimenTermsImportRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=100)
    version: str = Field(default="1.0.0", pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    approval_status: Literal["draft", "approved"] = "approved"
    allowed_roles: list[Literal["viewer", "operator", "auditor", "admin"]] = Field(
        default_factory=lambda: ["operator", "admin"], min_length=1, max_length=4
    )


class KnowledgeStatusRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=100)
    status: Literal["draft", "approved", "rejected", "superseded"]
    changed_by_role: str = Field(min_length=2, max_length=100)
    reason: str = Field(min_length=3, max_length=1000)


class KnowledgeEvaluationCase(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    expected_document_ids: list[str] = Field(min_length=1, max_length=20)


class KnowledgeEvaluationRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=100)
    cases: list[KnowledgeEvaluationCase] = Field(min_length=1, max_length=100)
    limit: int = Field(default=5, ge=1, le=20)
    language: Literal["en", "fa"] = "en"


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
    channel: Literal["email", "chat", "web", "phone", "social", "unknown"] = "unknown"
    priority: Literal["low", "normal", "high", "urgent"] = "normal"
    age_seconds: int = Field(default=0, ge=0)
    sla_seconds: int | None = Field(default=None, gt=0)
    prior_contact_count: int = Field(default=0, ge=0)


class SupportOutcome(BaseModel):
    ticket_id: str = Field(min_length=3, max_length=100)
    draft_outcome: Literal["accepted", "edited", "rejected", "not_used"]
    escalation_expected: bool
    escalation_performed: bool
    response_seconds: int = Field(ge=0)
    resolution_seconds: int = Field(ge=0)
    csat_score: int | None = Field(default=None, ge=1, le=5)


class SupportOutcomeEvaluationRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=100)
    outcomes: list[SupportOutcome] = Field(min_length=1, max_length=10000)


class KnowledgeQuestionRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=100)
    question: str = Field(min_length=2, max_length=1000)
    limit: int = Field(default=5, ge=1, le=20)
    language: Literal["en", "fa"] = "en"


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
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS xima_knowledge_status_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL, tenant_id TEXT NOT NULL, document_id TEXT NOT NULL,
            version TEXT NOT NULL, status TEXT NOT NULL, changed_by_role TEXT NOT NULL,
            reason TEXT NOT NULL, previous_hash TEXT NOT NULL, record_hash TEXT NOT NULL UNIQUE
        )
        """
    )
    return connection


def ingest_knowledge(path: str, request: KnowledgeDocumentRequest) -> tuple[int, dict]:
    receipt_id = str(uuid4())
    created_at = datetime.now(UTC).isoformat()
    content_hash = hashlib.sha256(request.content.encode()).hexdigest()
    with _connect(path) as connection:
        duplicate = connection.execute(
            "SELECT document_id,version FROM xima_knowledge WHERE tenant_id=? AND content_hash=? "
            "AND approval_status='approved'",
            (request.tenant_id, content_hash),
        ).fetchone()
        if duplicate and request.approval_status == "approved":
            return 409, {"code": "knowledge_duplicate_content",
                         "document_id": duplicate["document_id"], "version": duplicate["version"]}
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
        "chunk_count": len(chunk_knowledge(request.content)),
        "exchange_write_performed": False,
    }


def chunk_knowledge(content: str, size: int = 1200, overlap: int = 150) -> list[dict]:
    normalized = " ".join(content.split())
    chunks = []
    start = 0
    while start < len(normalized):
        end = min(len(normalized), start + size)
        if end < len(normalized):
            boundary = normalized.rfind(" ", start, end)
            if boundary > start:
                end = boundary
        text = normalized[start:end].strip()
        if text:
            chunks.append({"index": len(chunks), "start": start, "end": end,
                           "content_hash": hashlib.sha256(text.encode()).hexdigest(),
                           "preview": text[:240]})
        if end >= len(normalized):
            break
        start = max(end - overlap, start + 1)
    return chunks


def extract_document_text(filename: str, encoded: str) -> tuple[str, dict]:
    try:
        raw = base64.b64decode(encoded, validate=True)
    except ValueError as exc:
        raise ValueError("content_base64 is invalid") from exc
    if not raw or len(raw) > 10_000_000:
        raise ValueError("document must be between 1 byte and 10 MB")
    suffix = Path(filename).suffix.lower()
    if suffix in {".txt", ".md", ".csv", ".json"}:
        text = raw.decode("utf-8")
        processor = "utf8"
    elif suffix == ".docx":
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                xml = archive.read("word/document.xml")
            root = ElementTree.fromstring(xml)
            text = " ".join(node.text or "" for node in root.iter()
                            if node.tag.endswith("}t"))
        except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as exc:
            raise ValueError("DOCX document is invalid") from exc
        processor = "docx-openxml"
    elif suffix == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(raw))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception as exc:
            raise ValueError("PDF text extraction failed") from exc
        processor = "pypdf"
    else:
        raise ValueError("supported document types are TXT, Markdown, CSV, JSON, DOCX, and PDF")
    normalized = " ".join(text.split())
    if len(normalized) < 20:
        raise ValueError("document contains less than 20 characters of extractable text")
    if len(normalized) > 100000:
        raise ValueError("extracted document exceeds 100000 characters")
    return normalized, {"filename": filename, "bytes": len(raw), "processor": processor,
                        "chunks": chunk_knowledge(normalized)}


class _PolicyHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "svg", "noscript"}:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "svg", "noscript"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            text = " ".join(data.split())
            if text:
                self.parts.append(text)


def extract_policy_html(html: str) -> str:
    parser = _PolicyHTMLParser()
    parser.feed(html)
    text = "\n".join(dict.fromkeys(parser.parts))
    if len(text) < 100:
        raise ValueError("policy page contains insufficient extractable text")
    if len(text) > 100000:
        raise ValueError("policy page exceeds 100000 extractable characters")
    return text


def fetch_bitimen_page(source_url: Literal[
    "https://bitimen.com/terms/", "https://bitimen.com/how-to-use/"
]) -> tuple[str, dict]:
    request = Request(
        source_url,
        headers={"User-Agent": "bitAgent-knowledge-importer/1.0", "Accept": "text/html"},
    )
    with urlopen(request, timeout=20) as response:
        content_type = response.headers.get_content_type()
        raw = response.read(2_000_001)
    if content_type != "text/html":
        raise ValueError("Bitimen terms source did not return HTML")
    if len(raw) > 2_000_000:
        raise ValueError("Bitimen terms source exceeds 2 MB")
    text = extract_policy_html(raw.decode("utf-8"))
    return text, {
        "source_url": source_url,
        "processor": "allowlisted-html",
        "bytes": len(raw),
        "content_hash": hashlib.sha256(text.encode()).hexdigest(),
        "chunks": chunk_knowledge(text),
    }


def fetch_bitimen_terms() -> tuple[str, dict]:
    return fetch_bitimen_page(BITIMEN_TERMS_URL)


def fetch_bitimen_how_to_use() -> tuple[str, dict]:
    return fetch_bitimen_page(BITIMEN_HOW_TO_USE_URL)


def list_knowledge(path: str, tenant_id: str, role: str, include_content: bool = False) -> list[dict]:
    now = datetime.now(UTC)
    with _connect(path) as connection:
        rows = connection.execute(
            "SELECT * FROM xima_knowledge WHERE tenant_id=? ORDER BY document_id,id DESC",
            (tenant_id,),
        ).fetchall()
        events = connection.execute(
            "SELECT * FROM xima_knowledge_status_events WHERE tenant_id=? ORDER BY id DESC",
            (tenant_id,),
        ).fetchall()
    latest_status = {}
    for event in events:
        latest_status.setdefault((event["document_id"], event["version"]), event["status"])
    items = []
    for row in rows:
        allowed_roles = json.loads(row["allowed_roles_json"])
        if role not in allowed_roles and role != "admin":
            continue
        expires = datetime.fromisoformat(row["expires_at"])
        effective = datetime.fromisoformat(row["effective_at"])
        status = latest_status.get((row["document_id"], row["version"]), row["approval_status"])
        item = {key: row[key] for key in (
            "receipt_id", "created_at", "tenant_id", "document_id", "title",
            "document_type", "version", "owner", "data_class", "source_ref", "content_hash")}
        item.update({"status": status, "effective_at": row["effective_at"],
                     "expires_at": row["expires_at"], "allowed_roles": allowed_roles,
                     "keywords": json.loads(row["keywords_json"]),
                     "lifecycle": "expired" if expires <= now else
                                  "scheduled" if effective > now else "effective",
                     "chunks": chunk_knowledge(row["content"])})
        if include_content:
            item["content"] = row["content"]
        items.append(item)
    return items


def change_knowledge_status(path: str, document_id: str, version: str,
                            request: KnowledgeStatusRequest) -> tuple[int, dict]:
    created_at, event_id = datetime.now(UTC).isoformat(), str(uuid4())
    with _connect(path) as connection:
        document = connection.execute(
            "SELECT 1 FROM xima_knowledge WHERE tenant_id=? AND document_id=? AND version=?",
            (request.tenant_id, document_id, version),
        ).fetchone()
        if not document:
            return 404, {"code": "knowledge_document_not_found"}
        previous = connection.execute(
            "SELECT record_hash FROM xima_knowledge_status_events ORDER BY id DESC LIMIT 1"
        ).fetchone()
        previous_hash = previous["record_hash"] if previous else "0" * 64
        material = f"{request.tenant_id}\n{document_id}\n{version}\n{request.status}\n{request.changed_by_role}\n{request.reason}"
        record_hash = hashlib.sha256(
            f"{previous_hash}\n{created_at}\n{event_id}\n{material}".encode()
        ).hexdigest()
        connection.execute(
            "INSERT INTO xima_knowledge_status_events "
            "(event_id,created_at,tenant_id,document_id,version,status,changed_by_role,reason,previous_hash,record_hash) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (event_id, created_at, request.tenant_id, document_id, version, request.status,
             request.changed_by_role, request.reason, previous_hash, record_hash),
        )
    return 200, {"event_id": event_id, "document_id": document_id, "version": version,
                 "status": request.status, "record_hash": record_hash, "created_at": created_at,
                 "exchange_write_performed": False}


def _normalize_search_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = normalized.translate(str.maketrans({
        "ي": "ی", "ى": "ی", "ك": "ک", "ۀ": "ه", "ة": "ه",
        "ؤ": "و", "إ": "ا", "أ": "ا", "ٱ": "ا",
        "\u200c": " ", "\u200d": " ", "ـ": "",
    }))
    return "".join(
        character for character in normalized
        if unicodedata.category(character) != "Mn"
    )


def _terms(value: str) -> set[str]:
    tokens = re.findall(r"[^\W_]+", _normalize_search_text(value), flags=re.UNICODE)
    terms: set[str] = set()
    persian_suffixes = ("هایمان", "هایتان", "هایشان", "هایی", "های", "ها")
    for token in tokens:
        minimum = 2 if re.search(r"[\u0600-\u06ff]", token) else 3
        if len(token) < minimum:
            continue
        terms.add(token)
        for suffix in persian_suffixes:
            if token.endswith(suffix) and len(token) - len(suffix) >= 2:
                terms.add(token[:-len(suffix)])
                break
    return terms


def retrieve_knowledge(path: str, tenant_id: str, role: str, query: str, limit: int = 5) -> list[dict]:
    query_terms = _terms(query)
    results = []
    seen_documents = set()
    for item in list_knowledge(path, tenant_id, role, include_content=True):
        if item["document_id"] in seen_documents:
            continue
        if item["status"] != "approved" or item["lifecycle"] != "effective":
            continue
        searchable = _terms(f"{item['title']} {' '.join(item['keywords'])} {item['content']}")
        score = len(query_terms & searchable)
        if not score:
            continue
        seen_documents.add(item["document_id"])
        matched_terms = sorted(query_terms & searchable)
        results.append({
            "document_id": item["document_id"], "title": item["title"],
            "version": item["version"], "owner": item["owner"],
            "source_ref": item["source_ref"], "content_hash": item["content_hash"],
            "expires_at": item["expires_at"], "score": score,
            "matched_terms": matched_terms,
            "excerpt": item["content"][:500],
        })
    return sorted(results, key=lambda item: item["score"], reverse=True)[:limit]


def answer_knowledge_question(path: str, request: KnowledgeQuestionRequest, role: str) -> dict:
    citations = retrieve_knowledge(path, request.tenant_id, role, request.question, request.limit)
    if not citations:
        persian = request.language == "fa" or bool(re.search(
            r"[\u0600-\u06ff]", request.question
        ))
        return {
            "status": "insufficient_evidence", "answer": None, "citations": [],
            "confidence": "none",
            "language": "fa" if persian else "en",
            "limitations": [
                "هیچ سند مؤثر، تأییدشده و قابل‌دسترسی برای نقش کاربر با این پرسش مطابقت نداشت."
                if persian else
                "No effective, approved, role-accessible document matched the question."
            ],
            "human_review_required": True, "action_executed": False,
        }
    excerpts = "\n\n".join(
        f"[{item['title']} v{item['version']}] {item['excerpt']}" for item in citations
    )
    persian = request.language == "fa" or bool(re.search(
        r"[\u0600-\u06ff]", request.question
    ))
    return {
        "status": "answered", "answer": excerpts, "citations": citations,
        "language": "fa" if persian else "en",
        "confidence": "document_grounded",
        "limitations": [
            "این راهنمایی استخراجی است و عملیات صرافی یا تصمیم حقوقی محسوب نمی‌شود."
            if persian else
            "This is extractive guidance, not an exchange action or legal decision."
        ],
        "human_review_required": True, "action_executed": False,
    }


def evaluate_knowledge(path: str, request: KnowledgeEvaluationRequest, role: str) -> dict:
    results = []
    hits = 0
    reciprocal_rank_total = 0.0
    for case in request.cases:
        citations = retrieve_knowledge(
            path, request.tenant_id, role, case.question, request.limit
        )
        returned = [item["document_id"] for item in citations]
        ranks = [returned.index(expected) + 1 for expected in case.expected_document_ids
                 if expected in returned]
        hit = bool(ranks)
        hits += int(hit)
        reciprocal_rank_total += 1 / min(ranks) if ranks else 0
        results.append({"question": case.question,
                        "expected_document_ids": case.expected_document_ids,
                        "returned_document_ids": returned, "hit": hit,
                        "reciprocal_rank": 1 / min(ranks) if ranks else 0})
    count = len(results)
    return {"status": "passed" if hits == count else "needs_improvement",
            "language": request.language,
            "case_count": count, "hit_count": hits,
            "hit_rate": round(hits / count, 4),
            "mean_reciprocal_rank": round(reciprocal_rank_total / count, 4),
            "results": results, "action_executed": False}


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
                           "dissatisfaction": dissatisfaction, "escalate": escalate,
                           "channel": request.channel, "priority": request.priority,
                           "sla_breached": (request.sla_seconds is not None
                                            and request.age_seconds > request.sla_seconds)},
        "redacted_ticket": {"subject": safe_subject, "message": safe_message},
        "draft": draft, "citations": citations,
        "human_review_required": True, "send_enabled": False,
        "limitations": (["No approved matching knowledge was found."] if not citations else []),
        "recommended_next_action": (
            "Escalate to an authorized specialist." if escalate else
            "Review the cited draft before any response."
        ),
    }


def evaluate_support_outcomes(request: SupportOutcomeEvaluationRequest) -> dict:
    count = len(request.outcomes)
    escalation_correct = sum(
        item.escalation_expected == item.escalation_performed for item in request.outcomes
    )
    with_csat = [item.csat_score for item in request.outcomes if item.csat_score is not None]
    draft_counts = {state: sum(item.draft_outcome == state for item in request.outcomes)
                    for state in ("accepted", "edited", "rejected", "not_used")}
    return {"tenant_id": request.tenant_id, "status": "ready", "case_count": count,
            "draft_outcomes": draft_counts,
            "draft_acceptance_rate": round(draft_counts["accepted"] / count, 4),
            "escalation_accuracy": round(escalation_correct / count, 4),
            "average_response_seconds": round(sum(item.response_seconds for item in request.outcomes) / count, 2),
            "average_resolution_seconds": round(sum(item.resolution_seconds for item in request.outcomes) / count, 2),
            "average_csat": round(sum(with_csat) / len(with_csat), 2) if with_csat else None,
            "limitations": ["Metrics reflect submitted minimized outcomes only."],
            "action_executed": False}
