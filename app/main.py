import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from app import mock_data
from app.config import settings
from app.briefs import daily_executive_brief
from app.chat import (
    build_chat_context,
    build_prompt,
    answer_quality,
    citations,
    deterministic_answer,
    detects_prompt_injection,
    chat_rate_limiter,
    is_prohibited,
    intent_category,
    redact,
)
from app.exchange import ExchangeAPIError, exchange_client
from app.evidence import (
    evidence_trends,
    feedback_summary,
    chat_session_messages,
    chat_session_audit,
    recent_chat_audit,
    recent_access_decisions,
    recent_evidence,
    record_dashboard,
    record_feedback,
    record_access_decision,
    record_chat,
    verify_chain,
)
from app.features import FEATURES
from app.incidents import detect_withdrawal_slowdown
from app.investigations import withdrawal_investigation
from app.market_risk import analyze_market_range
from app.marketing import (
    AcquisitionPlanRequest,
    AutomationApprovalRequest,
    CampaignPlanRequest,
    ContentStudioRequest,
    EVENT_TAXONOMY,
    GOVERNANCE,
    LIFECYCLE_STAGES,
    MeasurementRequest,
    RetentionPlanRequest,
    SandboxExecutionRequest,
    audit_events,
    build_acquisition_plan,
    build_content_studio,
    build_measurement,
    build_retention_plan,
    create_automation_approval,
    create_plan,
    execute_sandbox,
    rollback_sandbox,
    set_automation_pause,
)
from app.ollama import OllamaError, ollama_client
from app.policy import evaluate_policy
from app.release_inputs import validate_release_inputs
from app.release_candidate import build_release_candidate_manifest
from app.readiness import (
    historical_replay,
    load_upstream_security_report,
    security_self_test,
    uat_readiness,
)

VERSION = "1.9.5"
ROOT = Path(__file__).parent

app = FastAPI(
    title="bitAgent",
    version=VERSION,
    description="Governed exchange operations and marketing planning tooling.",
)
app.mount(
    "/.well-known/acme-challenge",
    StaticFiles(directory="/acme-challenge", check_dir=False),
    name="acme-challenge",
)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


def authorize(capability: str, role: str | None) -> dict:
    enforced = settings.bitagent_access_control_mode == "enforced"
    decision = evaluate_policy(role, capability, enforced=enforced)
    decision["audit"] = record_access_decision(settings.evidence_db_path, decision)
    if enforced and not decision["allowed"]:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "access_denied",
                "capability": capability,
                "reason": decision["reason"],
                "decision_hash": decision["audit"]["decision_hash"],
            },
        )
    return decision


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/health")
async def health():
    return {"status": "ok", "version": VERSION, "mode": settings.bitagent_mode}


@app.get("/api/v0/status")
async def status():
    key_id, secret = settings.exchange_credentials()
    ollama_username, ollama_password = settings.ollama_credentials()
    return {
        "name": "bitAgent",
        "version": VERSION,
        "release": "Marketing Automation Sandbox",
        "mode": settings.bitagent_mode,
        "read_only": True,
        "base_url_configured": bool(settings.exchange_api_base_url),
        "key_id_configured": bool(key_id),
        "secret_configured": bool(secret),
        "timestamp": datetime.now(UTC).isoformat(),
        "access_control_mode": settings.bitagent_access_control_mode,
        "identity_proof": "pilot_role_header_only",
        "chat_enabled": settings.bitagent_chat_enabled,
        "llm": {
            "provider": settings.llm_provider,
            "base_url_configured": bool(settings.ollama_base_url),
            "model": settings.ollama_model,
            "basic_auth_configured": bool(ollama_username and ollama_password),
        },
    }


@app.get("/api/v0/marketing/foundation")
async def marketing_foundation(
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    authorize("view_marketing", role)
    return {
        "version": VERSION,
        "governance": GOVERNANCE,
        "lifecycle_stages": LIFECYCLE_STAGES,
        "event_taxonomy": EVENT_TAXONOMY,
        "action_executed": False,
    }


@app.post("/api/v0/marketing/plans", status_code=201)
async def marketing_plan(
    request: CampaignPlanRequest,
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    decision = authorize("create_marketing_plan", role)
    if not decision["allowed"]:
        raise HTTPException(status_code=403, detail={"code": "marketing_role_denied"})
    return {"version": VERSION, "plan": create_plan(settings.evidence_db_path, request)}


@app.post("/api/v0/marketing/acquisition-plans", status_code=201)
async def acquisition_plan(
    request: AcquisitionPlanRequest,
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    decision = authorize("create_marketing_plan", role)
    if not decision["allowed"]:
        raise HTTPException(status_code=403, detail={"code": "marketing_role_denied"})
    return {
        "version": VERSION,
        "plan": build_acquisition_plan(settings.evidence_db_path, request),
    }


@app.post("/api/v0/marketing/retention-plans", status_code=201)
async def retention_plan(
    request: RetentionPlanRequest,
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    decision = authorize("create_marketing_plan", role)
    if not decision["allowed"]:
        raise HTTPException(status_code=403, detail={"code": "marketing_role_denied"})
    return {
        "version": VERSION,
        "plan": build_retention_plan(settings.evidence_db_path, request),
    }


@app.post("/api/v0/marketing/content", status_code=201)
async def marketing_content(
    request: ContentStudioRequest,
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    decision = authorize("create_marketing_plan", role)
    if not decision["allowed"]:
        raise HTTPException(status_code=403, detail={"code": "marketing_role_denied"})
    return {
        "version": VERSION,
        "artifact": build_content_studio(settings.evidence_db_path, request),
    }


@app.post("/api/v0/marketing/measurements", status_code=201)
async def marketing_measurement(
    request: MeasurementRequest,
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    decision = authorize("create_marketing_plan", role)
    if not decision["allowed"]:
        raise HTTPException(status_code=403, detail={"code": "marketing_role_denied"})
    return {
        "version": VERSION,
        "report": build_measurement(settings.evidence_db_path, request),
    }


@app.post("/api/v0/marketing/automation/approvals", status_code=201)
async def automation_approval(
    request: AutomationApprovalRequest,
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    decision = authorize("manage_marketing_automation", role)
    if not decision["allowed"]:
        raise HTTPException(status_code=403, detail={"code": "automation_role_denied"})
    return {"version": VERSION, "approval": create_automation_approval(settings.evidence_db_path, request)}


@app.post("/api/v0/marketing/automation/dry-runs")
async def automation_dry_run(
    request: SandboxExecutionRequest,
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    decision = authorize("manage_marketing_automation", role)
    if not decision["allowed"]:
        raise HTTPException(status_code=403, detail={"code": "automation_role_denied"})
    status_code, result = execute_sandbox(settings.evidence_db_path, request)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=result)
    return {"version": VERSION, "execution": result}


@app.post("/api/v0/marketing/automation/executions/{execution_id}/rollback")
async def automation_rollback(
    execution_id: str,
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    decision = authorize("manage_marketing_automation", role)
    if not decision["allowed"]:
        raise HTTPException(status_code=403, detail={"code": "automation_role_denied"})
    status_code, result = rollback_sandbox(settings.evidence_db_path, execution_id)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=result)
    return {"version": VERSION, "execution": result}


@app.post("/api/v0/marketing/automation/pause")
async def automation_pause(
    paused: bool,
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    decision = authorize("manage_marketing_automation", role)
    if not decision["allowed"]:
        raise HTTPException(status_code=403, detail={"code": "automation_role_denied"})
    return {"version": VERSION, **set_automation_pause(settings.evidence_db_path, paused)}


@app.get("/api/v0/marketing/audit")
async def marketing_audit(
    limit: int = Query(default=50, ge=1, le=500),
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    decision = authorize("view_marketing_audit", role)
    if not decision["allowed"]:
        raise HTTPException(status_code=403, detail={"code": "marketing_audit_role_denied"})
    return {"version": VERSION, "items": audit_events(settings.evidence_db_path, limit)}


@app.get("/api/v0/features")
async def features(
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    authorize("view_features", role)
    counts = {
        state: sum(feature["status"] == state for feature in FEATURES)
        for state in ("available", "partial", "missing")
    }
    return {"version": VERSION, "counts": counts, "items": FEATURES}


async def fetch_dashboard(market: str, days: int) -> tuple[dict, dict]:
    if settings.bitagent_mode == "mock":
        return mock_data.operations(days), mock_data.market(market)
    now = datetime.now(UTC)
    params = {
        "date_from": (now - timedelta(days=days)).date().isoformat(),
        "date_to": now.date().isoformat(),
    }
    operations = await exchange_client.get("/api/bot/operations", params)
    market_data = await exchange_client.get(
        f"/api/bot/market/{market}/summary"
    )
    return operations, market_data


@app.get("/api/v0/dashboard")
async def dashboard(
    market: str = Query(default=settings.bitagent_default_market, pattern=r"^[A-Z0-9]+_[A-Z0-9]+$"),
    days: int = Query(default=30, ge=1, le=366),
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    authorize("view_aggregate", role)
    try:
        operations, market_data = await fetch_dashboard(market, days)
    except ExchangeAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    pending = int(operations.get("data", {}).get("pending_withdrawals", 0))
    incident = detect_withdrawal_slowdown(
        operations,
        warning_threshold=settings.withdrawal_pending_warning_threshold,
        critical_threshold=settings.withdrawal_pending_critical_threshold,
    )
    market_risk = analyze_market_range(
        market_data,
        warning_percent=settings.market_range_warning_percent,
        critical_percent=settings.market_range_critical_percent,
    )
    payload = {
        "version": VERSION,
        "mode": settings.bitagent_mode,
        "operations": operations,
        "market": market_data,
        "incident": incident,
        "market_risk": market_risk,
        "signals": [
            {
                "severity": "warning" if pending else "healthy",
                "title": "Pending withdrawals",
                "value": pending,
                "explanation": (
                    "Pending withdrawals need investigation. Version 0 cannot "
                    "yet determine age, queue backlog, worker state or root cause."
                    if pending
                    else "No pending withdrawals reported for this period."
                ),
            }
        ],
    }
    payload["evidence_record"] = record_dashboard(settings.evidence_db_path, payload)
    return payload


@app.get("/api/v0/evidence/recent")
async def evidence_recent(
    limit: int = Query(default=20, ge=1, le=100),
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    authorize("view_aggregate", role)
    return {"version": VERSION, "items": recent_evidence(settings.evidence_db_path, limit)}


@app.get("/api/v0/audit/verify")
async def audit_verify(
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    authorize("view_audit", role)
    return {"version": VERSION, **verify_chain(settings.evidence_db_path)}


@app.get("/api/v0/trends")
async def trends(
    limit: int = Query(default=30, ge=2, le=1000),
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    authorize("view_aggregate", role)
    return {
        "version": VERSION,
        **evidence_trends(
            settings.evidence_db_path,
            limit,
            settings.evidence_freshness_warning_seconds,
        ),
    }


@app.get("/api/v0/investigations/withdrawal-slowdown")
async def investigate_withdrawal_slowdown(
    trend_limit: int = Query(default=30, ge=2, le=1000),
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    authorize("view_brief", role)
    return {
        "version": VERSION,
        **withdrawal_investigation(
            settings.evidence_db_path,
            trend_limit=trend_limit,
            freshness_warning_seconds=settings.evidence_freshness_warning_seconds,
        ),
    }


@app.get("/api/v0/briefs/daily")
async def daily_brief(
    trend_limit: int = Query(default=30, ge=2, le=1000),
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    authorize("view_brief", role)
    return {
        "version": VERSION,
        **daily_executive_brief(
            settings.evidence_db_path,
            trend_limit=trend_limit,
            freshness_warning_seconds=settings.evidence_freshness_warning_seconds,
        ),
    }


class FeedbackRequest(BaseModel):
    report_id: str = Field(min_length=1, max_length=200)
    rating: Literal["useful", "not_useful", "needs_correction"]
    comment: str = Field(default="", max_length=1000)


@app.post("/api/v0/feedback", status_code=201)
async def submit_feedback(
    feedback: FeedbackRequest,
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    authorize("submit_feedback", role)
    return {
        "version": VERSION,
        "feedback": record_feedback(
            settings.evidence_db_path,
            feedback.report_id,
            feedback.rating,
            feedback.comment.strip(),
        ),
        "exchange_write_performed": False,
    }


@app.get("/api/v0/feedback/summary")
async def get_feedback_summary(
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    authorize("view_brief", role)
    return {"version": VERSION, **feedback_summary(settings.evidence_db_path)}


class PolicyEvaluationRequest(BaseModel):
    capability: str = Field(min_length=1, max_length=100)


@app.post("/api/v0/policy/evaluate")
async def policy_evaluate(
    request: PolicyEvaluationRequest,
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    decision = evaluate_policy(
        role,
        request.capability,
        enforced=settings.bitagent_access_control_mode == "enforced",
    )
    decision["audit"] = record_access_decision(settings.evidence_db_path, decision)
    return {"version": VERSION, "decision": decision}


class ChatRequest(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    session_id: UUID = Field(default_factory=uuid4)

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        if any(ord(character) < 32 for character in value):
            raise ValueError("control characters are not allowed")
        normalized = " ".join(value.split())
        if len(normalized) < 2:
            raise ValueError("question must contain meaningful text")
        return normalized


@app.post("/api/v0/chat")
async def readonly_chat(
    request: ChatRequest,
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    decision = authorize("use_readonly_chat", role)
    if not decision["allowed"]:
        raise HTTPException(
            status_code=403,
            detail={"code": "chat_role_denied", "reason": decision["reason"]},
        )
    normalized_role = decision["role"]
    session_id = str(request.session_id)
    allowed, retry_after = chat_rate_limiter.check(
        f"{normalized_role}:{session_id}", settings.chat_requests_per_minute
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "chat_rate_limited",
                "retry_after_seconds": retry_after,
            },
        )
    question = redact(request.question.strip())
    context = build_chat_context(
        settings.evidence_db_path,
        trend_limit=30,
        freshness_warning_seconds=settings.evidence_freshness_warning_seconds,
    )
    if not context:
        raise HTTPException(
            status_code=409,
            detail={"code": "insufficient_evidence", "message": "Refresh the dashboard first."},
        )

    evidence_record_id = context["evidence_record"]["id"]
    if detects_prompt_injection(question):
        answer = (
            "I cannot follow instructions that attempt to override policy or reveal "
            "hidden prompts. Ask a direct question about retained evidence instead. "
            "No action executed by bitAgent."
        )
        evidence_citations = citations(context)
        quality = answer_quality(answer, evidence_citations)
        audit = record_chat(
            settings.evidence_db_path,
            role=normalized_role,
            model="safety-refusal",
            question=question,
            answer=answer,
            evidence_record_id=evidence_record_id,
            success=True,
            error_code="prompt_injection_refused",
            session_id=session_id,
        )
        return {
            "version": VERSION,
            "session_id": session_id,
            "answer_type": "safety_refusal",
            "category": "safety",
            "answer": answer,
            "citations": evidence_citations,
            "quality": quality,
            "confidence": "policy_certain",
            "limitations": context["investigation"].get("limitations", []),
            "model": "safety-refusal",
            "intent": "prompt_injection_refusal",
            "audit": audit,
            "evidence_record": context["evidence_record"],
            "action_executed": False,
        }

    if is_prohibited(question):
        answer = (
            "I cannot perform or assist with exchange write actions. I can only "
            "explain retained read-only evidence and suggest human investigation. "
            "No action executed by bitAgent."
        )
        evidence_citations = citations(context)
        quality = answer_quality(answer, evidence_citations)
        audit = record_chat(
            settings.evidence_db_path,
            role=normalized_role,
            model="policy-refusal",
            question=question,
            answer=answer,
            evidence_record_id=evidence_record_id,
            success=True,
            error_code="prohibited_action_refused",
            session_id=session_id,
        )
        return {
            "version": VERSION,
            "session_id": session_id,
            "answer_type": "policy_refusal",
            "category": "safety",
            "answer": answer,
            "citations": evidence_citations,
            "quality": quality,
            "confidence": "policy_certain",
            "limitations": context["investigation"].get("limitations", []),
            "model": "policy-refusal",
            "audit": audit,
            "evidence_record": context["evidence_record"],
            "action_executed": False,
        }

    deterministic = deterministic_answer(question, context)
    if deterministic:
        answer = (
            f"{deterministic['answer']}\n\nNo action executed by bitAgent."
        )
        model = "deterministic-evidence-v1"
        evidence_citations = citations(context)
        quality = answer_quality(answer, evidence_citations)
        audit = record_chat(
            settings.evidence_db_path,
            role=normalized_role,
            model=model,
            question=question,
            answer=answer,
            evidence_record_id=evidence_record_id,
            success=True,
            session_id=session_id,
        )
        return {
            "version": VERSION,
            "session_id": session_id,
            "answer_type": "deterministic",
            "category": intent_category(deterministic["intent"]),
            "answer": answer,
            "citations": evidence_citations,
            "quality": quality,
            "confidence": deterministic["confidence"],
            "limitations": context["investigation"].get("limitations", []),
            "model": model,
            "intent": deterministic["intent"],
            "audit": audit,
            "evidence_record": context["evidence_record"],
            "action_executed": False,
        }

    try:
        generated = await ollama_client.generate(
            build_prompt(
                question,
                context,
                max_context_chars=settings.chat_context_max_chars,
            )
        )
    except OllamaError as exc:
        record_chat(
            settings.evidence_db_path,
            role=normalized_role,
            model=settings.ollama_model,
            question=question,
            answer="",
            evidence_record_id=evidence_record_id,
            success=False,
            error_code="ollama_unavailable",
            session_id=session_id,
        )
        raise HTTPException(
            status_code=503,
            detail={"code": "chat_unavailable", "message": str(exc)},
        ) from exc

    answer = redact(generated["answer"])
    if "No action executed by bitAgent." not in answer:
        answer = f"{answer}\n\nNo action executed by bitAgent."
    evidence_citations = citations(context)
    quality = answer_quality(answer, evidence_citations)
    if not quality["passed"]:
        raise HTTPException(
            status_code=502,
            detail={"code": "chat_quality_gate_failed", "checks": quality["checks"]},
        )
    audit = record_chat(
        settings.evidence_db_path,
        role=normalized_role,
        model=generated["model"],
        question=question,
        answer=answer,
        evidence_record_id=evidence_record_id,
        success=True,
        session_id=session_id,
    )
    return {
        "version": VERSION,
        "session_id": session_id,
        "answer_type": "llm",
        "category": "open_ended",
        "answer": answer,
        "citations": evidence_citations,
        "quality": quality,
        "confidence": context["investigation"].get("confidence", "insufficient"),
        "limitations": context["investigation"].get("limitations", []),
        "model": generated["model"],
        "usage": {
            "prompt_tokens": generated["prompt_tokens"],
            "response_tokens": generated["response_tokens"],
        },
        "audit": audit,
        "evidence_record": context["evidence_record"],
        "action_executed": False,
    }


@app.get("/api/v0/chat/health")
async def chat_health(
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    decision = authorize("use_readonly_chat", role)
    if not decision["allowed"]:
        raise HTTPException(status_code=403, detail={"code": "chat_role_denied"})
    username, password = settings.ollama_credentials()
    evidence_available = bool(recent_evidence(settings.evidence_db_path, 1))
    chain = verify_chain(settings.evidence_db_path)
    return {
        "version": VERSION,
        "status": "operational" if chain["valid"] else "degraded",
        "read_only": True,
        "deterministic_answers_available": evidence_available,
        "evidence_available": evidence_available,
        "audit_chain_valid": chain["valid"],
        "ollama": {
            "enabled": settings.bitagent_chat_enabled,
            "base_url_configured": bool(settings.ollama_base_url),
            "model_configured": bool(settings.ollama_model),
            "basic_auth_configured": bool(username and password),
        },
    }


@app.get("/api/v0/chat/models")
async def chat_models(
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    decision = authorize("use_readonly_chat", role)
    if not decision["allowed"]:
        raise HTTPException(status_code=403, detail={"code": "chat_role_denied"})
    try:
        models = await ollama_client.models()
        resolved = await ollama_client.resolve_model(models)
    except OllamaError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "ollama_unavailable", "message": str(exc)},
        ) from exc
    return {
        "version": VERSION,
        "configured": settings.ollama_model,
        "resolved": resolved,
        "models": models,
    }


@app.get("/api/v0/chat/sessions/{session_id}")
async def chat_session_history(
    session_id: UUID,
    limit: int = Query(default=50, ge=1, le=100),
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    decision = authorize("use_readonly_chat", role)
    if not decision["allowed"]:
        raise HTTPException(status_code=403, detail={"code": "chat_role_denied"})
    items = chat_session_messages(
        settings.evidence_db_path,
        str(session_id),
        role=decision["role"],
        limit=limit,
    )
    return {
        "version": VERSION,
        "session_id": str(session_id),
        "items": items,
        "count": len(items),
    }


@app.get("/api/v0/chat/sessions/{session_id}/export")
async def chat_session_export(
    session_id: UUID,
    limit: int = Query(default=100, ge=1, le=500),
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    decision = authorize("use_readonly_chat", role)
    if not decision["allowed"]:
        raise HTTPException(status_code=403, detail={"code": "chat_role_denied"})
    items = chat_session_messages(
        settings.evidence_db_path,
        str(session_id),
        role=decision["role"],
        limit=limit,
    )
    receipt = hashlib.sha256(
        json.dumps(items, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "version": VERSION,
        "session_id": str(session_id),
        "items": items,
        "count": len(items),
        "receipt_sha256": receipt,
        "action_executed": False,
    }


@app.get("/api/v0/audit/chat/recent")
async def chat_audit_recent(
    limit: int = Query(default=50, ge=1, le=500),
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    decision = authorize("view_chat_audit", role)
    if not decision["allowed"]:
        raise HTTPException(status_code=403, detail={"code": "chat_audit_role_denied"})
    return {
        "version": VERSION,
        "items": recent_chat_audit(settings.evidence_db_path, limit),
    }


@app.get("/api/v0/audit/chat/sessions/{session_id}")
async def chat_session_audit_receipts(
    session_id: UUID,
    limit: int = Query(default=100, ge=1, le=500),
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    decision = authorize("view_chat_audit", role)
    if not decision["allowed"]:
        raise HTTPException(status_code=403, detail={"code": "chat_audit_role_denied"})
    items = chat_session_audit(
        settings.evidence_db_path, str(session_id), limit
    )
    return {
        "version": VERSION,
        "session_id": str(session_id),
        "items": items,
        "count": len(items),
        "content_exposed": False,
    }


@app.get("/api/v0/audit/access/recent")
async def access_audit_recent(
    limit: int = Query(default=50, ge=1, le=500),
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    authorize("view_audit", role)
    return {
        "version": VERSION,
        "items": recent_access_decisions(settings.evidence_db_path, limit),
    }


@app.get("/api/v0/evaluations/replay")
async def replay_evaluation(
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    authorize("view_audit", role)
    return {
        "version": VERSION,
        **historical_replay(
            settings.withdrawal_pending_warning_threshold,
            settings.withdrawal_pending_critical_threshold,
        ),
    }


@app.get("/api/v0/readiness")
async def readiness_report(
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    authorize("view_audit", role)
    replay = historical_replay(
        settings.withdrawal_pending_warning_threshold,
        settings.withdrawal_pending_critical_threshold,
    )
    security = security_self_test(verify_chain(settings.evidence_db_path))
    upstream_security = load_upstream_security_report(
        settings.upstream_security_report_path
    )
    release_inputs = validate_release_inputs(
        settings.release_evidence_directory,
        warning_threshold=settings.withdrawal_pending_warning_threshold,
        critical_threshold=settings.withdrawal_pending_critical_threshold,
    )
    return {
        "version": VERSION,
        "replay": replay,
        "security": security,
        "uat": uat_readiness(
            replay,
            security,
            live_mode=settings.bitagent_mode == "live",
            upstream_security=upstream_security,
            release_inputs=release_inputs,
        ),
        "upstream_security": upstream_security,
        "release_inputs": release_inputs,
    }


@app.get("/api/v0/releases/candidate")
async def release_candidate(
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    report = await readiness_report(role)
    return build_release_candidate_manifest(
        report["uat"], current_version=VERSION
    )


UserResource = Literal[
    "summary", "balances", "trades", "deposits", "withdrawals", "pnl"
]


@app.get("/api/v0/users/{user_id}/{resource}")
async def user_resource(
    user_id: int,
    resource: UserResource,
    date_from: str | None = None,
    date_to: str | None = None,
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    authorize("view_user_investigation", role)
    if settings.bitagent_mode == "mock":
        return {
            "mode": "mock",
            "data": {"user_id": user_id, "resource": resource, "items": []},
            "meta": {
                "generated_at": datetime.now(UTC).isoformat(),
                "notice": "No user-level fixture is included to avoid sample PII.",
            },
        }
    params = {
        key: value
        for key, value in {"date_from": date_from, "date_to": date_to}.items()
        if value
    }
    try:
        return await exchange_client.get(
            f"/api/bot/user/{user_id}/{resource}", params or None
        )
    except ExchangeAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
