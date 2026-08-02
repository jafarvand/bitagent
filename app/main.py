import asyncio
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
from app.exchange_v08 import (
    ExchangeContractError, analyze_transaction_flow, reconcile_treasury,
    summarize_user_investigation,
)
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
    PilotApprovalRequest,
    PilotScheduleRequest,
    RetentionPlanRequest,
    SandboxExecutionRequest,
    audit_events,
    build_acquisition_plan,
    build_content_studio,
    build_measurement,
    build_retention_plan,
    create_automation_approval,
    create_plan,
    create_pilot_approval,
    cancel_pilot,
    execute_sandbox,
    rollback_sandbox,
    pilot_monitoring,
    schedule_pilot,
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
from app.xima import (
    EvidenceEnvelope, ingest_evidence, recent_xima_outputs, record_xima_output,
    replay_evidence, source_health, verify_xima_chain, verify_xima_output_chain,
)
from app.xima_operations import OperationsAnalysisRequest, analyze_operations
from app.xima_market import MarketRiskRequest as XimaMarketRiskRequest, analyze_market_risk as analyze_xima_market_risk
from app.xima_treasury import TreasuryAnalysisRequest, analyze_treasury
from app.xima_aml import AMLAnalysisRequest, AMLFeedbackRequest, analyze_aml, record_aml_feedback
from app.xima_security import SecurityAnalysisRequest, analyze_security
from app.xima_support import (
    KnowledgeDocumentRequest, KnowledgeEvaluationRequest, KnowledgeQuestionRequest,
    KnowledgeStatusRequest, KnowledgeUploadRequest, SupportTicketRequest,
    analyze_support, answer_knowledge_question, change_knowledge_status,
    evaluate_knowledge, extract_document_text, ingest_knowledge, list_knowledge,
    retrieve_knowledge,
)
from app.xima_governance import (
    EvaluationRequest as XimaEvaluationRequest, RegistryEntryRequest,
    XimaPolicyRequest, evaluate_quality, evaluate_xima_policy, register_component,
)
from app.xima_shadow import ShadowPilotRequest, evaluate_shadow_pilot
from app.xima_actions import (
    ActionAuthorizationRequest, ActionExecutionRequest, ActionPreviewRequest,
    authorize_preview, create_preview, execute_action, rollback_action, set_kill_switch,
)
from app.xima_executive import ExecutiveBriefRequest, build_executive_brief

VERSION = "2.14.0"
EXCHANGE_API_VERSION = "0.8.0-pilot"
EXCHANGE_VERSION_COVERAGE = [
    {"version": "0.1", "status": "rejected", "capability": "Bearer secret on wire", "evidence": "Superseded as insecure; never enabled"},
    {"version": "0.2", "status": "implemented", "capability": "Key-ID HMAC, signed query/body, nonce replay protection", "evidence": "app/exchange.py + signature tests"},
    {"version": "0.3", "status": "implemented", "capability": "Pending withdrawals and six user investigation reads", "evidence": "/api/v0/exchange/users/{user_id}/investigation"},
    {"version": "0.4", "status": "implemented", "capability": "Full envelope, scopes, quality, lineage, structured errors", "evidence": "app/exchange_v08.py fail-closed validation"},
    {"version": "0.5", "status": "implemented", "capability": "Cursor-paginated pending deposits", "evidence": "/api/v0/exchange/transaction-intelligence"},
    {"version": "0.6", "status": "external", "capability": "Isolated synthetic staging environment", "evidence": "https://staging-devapi.zekabot.com; exchange-owned credentials required"},
    {"version": "0.7", "status": "implemented", "capability": "Aggregate ledger liabilities", "evidence": "/api/v0/exchange/treasury-intelligence"},
    {"version": "0.8", "status": "implemented", "capability": "Treasury crypto/fiat assets and quality warnings", "evidence": "/api/v0/exchange/treasury-intelligence"},
]
AGENT_CHAT_DEFINITIONS = {
    "operations": {
        "name": "Operations Agent", "description": "Exchange health, transaction flow, backlogs, incidents, and runbooks.",
        "samples": ["How many withdrawals are pending?", "What changed in the retained withdrawal trend?", "What evidence limits the current root-cause conclusion?"],
    },
    "market-risk": {
        "name": "Market & Risk Agent", "description": "Market snapshots, range quality, liquidity limitations, and risk evidence.",
        "samples": ["What is the current market-range risk?", "Is the latest market snapshot complete?", "What liquidity evidence is still unavailable?"],
    },
    "treasury": {
        "name": "Treasury Agent", "description": "Assets, liabilities, custody quality, coverage, and reconciliation boundaries.",
        "samples": ["What treasury evidence is currently available?", "Are assets and liabilities fully reconciled?", "What prevents a proof-of-reserves conclusion?"],
    },
    "aml-fraud": {
        "name": "AML & Fraud Agent", "description": "Governed case evidence, risk factors, queues, and mandatory human review.",
        "samples": ["What AML evidence is available to this agent?", "Can the current evidence support a fraud conclusion?", "Which AML decisions require human review?"],
    },
    "security": {
        "name": "Security Agent", "description": "Authentication, privileged activity, security incidents, and access boundaries.",
        "samples": ["Is the retained evidence chain valid?", "What security telemetry is still missing?", "Can this agent reveal API keys or secrets?"],
    },
    "support": {
        "name": "Support Agent", "description": "Safe evidence explanations, escalation, governed knowledge, and PII boundaries.",
        "samples": ["Explain the withdrawal warning for a support operator.", "What can I tell a customer without exposing private data?", "When should this issue be escalated?"],
    },
    "executive": {
        "name": "Executive Agent", "description": "Cross-domain priorities, readiness, confidence, limitations, and owner actions.",
        "samples": ["Give me the current executive brief.", "What are today's highest priorities?", "Is the system ready for unrestricted go-live?"],
    },
    "governance": {
        "name": "Governance Agent", "description": "Policy, auditability, readiness gates, prohibited actions, and evidence quality.",
        "samples": ["Which capability gaps remain?", "What does the audit chain prove?", "Can bitAgent execute a withdrawal or change a balance?"],
    },
}
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


@app.get("/exchange-api-test", include_in_schema=False)
async def exchange_api_test_page():
    return FileResponse(ROOT / "static" / "exchange-api-test.html")


@app.get("/agents", include_in_schema=False)
async def agent_chat_hub():
    return FileResponse(ROOT / "static" / "agent-chat.html")


@app.get("/agents/{agent_domain}", include_in_schema=False)
async def agent_chat_page(agent_domain: str):
    if agent_domain not in AGENT_CHAT_DEFINITIONS:
        raise HTTPException(status_code=404, detail="Unknown agent")
    return FileResponse(ROOT / "static" / "agent-chat.html")


@app.get("/knowledge", include_in_schema=False)
async def knowledge_workspace():
    return FileResponse(ROOT / "static" / "knowledge.html")


@app.get("/api/v0/agents")
async def agent_chat_catalog(
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    authorize("view_features", role)
    return {
        "version": VERSION,
        "agents": [
            {"id": agent_id, **definition, "path": f"/agents/{agent_id}"}
            for agent_id, definition in AGENT_CHAT_DEFINITIONS.items()
        ],
        "count": len(AGENT_CHAT_DEFINITIONS),
        "action_executed": False,
    }


EXCHANGE_API_TESTS = [
    ("health", "Platform", "/api/bot/health"),
    ("transactions", "Operations", "/api/bot/transactions/summary"),
    ("withdrawals", "Operations", "/api/bot/withdrawals/pending"),
    ("deposits", "Operations", "/api/bot/deposits/pending"),
    ("operations", "Operations", "/api/bot/operations"),
    ("market-summary", "Market", "/api/bot/market/{market}/summary"),
    ("liabilities", "Treasury", "/api/bot/ledger/liabilities"),
    ("treasury-assets", "Treasury", "/api/bot/treasury/assets"),
    ("user-summary", "User", "/api/bot/user/{user_id}/summary"),
    ("user-balances", "User", "/api/bot/user/{user_id}/balances"),
    ("user-trades", "User", "/api/bot/user/{user_id}/trades"),
    ("user-deposits", "User", "/api/bot/user/{user_id}/deposits"),
    ("user-withdrawals", "User", "/api/bot/user/{user_id}/withdrawals"),
    ("user-pnl", "User", "/api/bot/user/{user_id}/pnl"),
]


class ExchangeAPITestRequest(BaseModel):
    test_id: str = Field(min_length=1, max_length=80)
    market: str = Field(default="BTC_USDT", pattern=r"^[A-Z0-9]+_[A-Z0-9]+$")
    user_id: int = Field(default=1, ge=1)
    limit: int = Field(default=10, ge=1, le=100)


def summarize_exchange_test_response(payload: dict) -> dict:
    data = payload.get("data")
    summary = {
        "schema": payload.get("schema"),
        "source_id": payload.get("source_id"),
        "observed_at": payload.get("observed_at"),
        "generated_at": payload.get("generated_at"),
        "freshness_sla_seconds": payload.get("freshness_sla_seconds"),
        "quality": payload.get("quality"),
        "request_id": payload.get("request_id"),
        "data_type": type(data).__name__,
    }
    if isinstance(data, dict):
        summary["data_keys"] = sorted(data.keys())
        summary["collection_counts"] = {
            key: len(value) for key, value in data.items() if isinstance(value, list)
        }
    elif isinstance(data, list):
        summary["item_count"] = len(data)
    return summary


@app.get("/api/v0/exchange-tests")
async def exchange_tests(
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    authorize("view_xima", role)
    return {
        "version": VERSION,
        "exchange_api_version": EXCHANGE_API_VERSION,
        "mode": settings.bitagent_mode,
        "exchange_base_url": settings.exchange_api_base_url,
        "credentials_exposed": False,
        "tests": [
            {"id": test_id, "group": group, "method": "GET", "path": path}
            for test_id, group, path in EXCHANGE_API_TESTS
        ],
    }


@app.get("/api/v0/exchange/version-coverage")
async def exchange_version_coverage(
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    authorize("view_features", role)
    return {
        "version": VERSION,
        "exchange_api_version": EXCHANGE_API_VERSION,
        "coverage": EXCHANGE_VERSION_COVERAGE,
        "implemented_versions": [
            item["version"] for item in EXCHANGE_VERSION_COVERAGE
            if item["status"] == "implemented"
        ],
        "action_executed": False,
    }


@app.post("/api/v0/exchange-tests/run")
async def run_exchange_test(
    request: ExchangeAPITestRequest,
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    authorize("view_xima", role)
    selected = next((item for item in EXCHANGE_API_TESTS if item[0] == request.test_id), None)
    if selected is None:
        raise HTTPException(status_code=404, detail="Unknown exchange API test")
    _, group, template = selected
    path = template.format(market=request.market, user_id=request.user_id)
    now = datetime.now(UTC)
    date_params = {
        "date_from": (now - timedelta(days=7)).date().isoformat(),
        "date_to": now.date().isoformat(),
    }
    params = None
    if request.test_id == "operations":
        params = date_params
    elif request.test_id in {"withdrawals", "deposits"}:
        params = {"limit": request.limit}
    elif request.test_id in {"user-trades", "user-deposits", "user-withdrawals"}:
        params = {**date_params, "limit": request.limit}
    elif request.test_id == "user-pnl":
        params = date_params
    started = datetime.now(UTC)
    try:
        payload = await exchange_client.get(path, params)
        return {
            "ok": True, "group": group, "method": "GET", "path": path,
            "query": params or {}, "exchange_api_version": EXCHANGE_API_VERSION,
            "duration_ms": round((datetime.now(UTC) - started).total_seconds() * 1000, 2),
            "response_summary": summarize_exchange_test_response(payload),
            "sensitive_exchange_data_exposed": False,
        }
    except ExchangeAPIError as exc:
        return {
            "ok": False, "group": group, "method": "GET", "path": path,
            "query": params or {}, "exchange_api_version": EXCHANGE_API_VERSION,
            "duration_ms": round((datetime.now(UTC) - started).total_seconds() * 1000, 2),
            "error": str(exc),
        }


@app.get("/api/v0/exchange/transaction-intelligence")
async def exchange_transaction_intelligence(
    limit: int = Query(default=25, ge=1, le=100),
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    authorize("view_aggregate", role)
    try:
        if settings.bitagent_mode == "mock":
            payloads = (
                mock_data.health(), mock_data.transactions_summary(),
                mock_data.pending("withdrawals"), mock_data.pending("deposits"),
            )
        else:
            payloads = await asyncio.gather(
                exchange_client.get("/api/bot/health"),
                exchange_client.get("/api/bot/transactions/summary"),
                exchange_client.get("/api/bot/withdrawals/pending", {"limit": limit}),
                exchange_client.get("/api/bot/deposits/pending", {"limit": limit}),
            )
        return {
            "version": VERSION, "exchange_api_version": EXCHANGE_API_VERSION,
            **analyze_transaction_flow(*payloads),
        }
    except (ExchangeAPIError, ExchangeContractError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/v0/exchange/treasury-intelligence")
async def exchange_treasury_intelligence(
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    authorize("view_xima", role)
    try:
        if settings.bitagent_mode == "mock":
            liabilities, treasury = mock_data.liabilities(), mock_data.treasury_assets()
        else:
            liabilities, treasury = await asyncio.gather(
                exchange_client.get("/api/bot/ledger/liabilities"),
                exchange_client.get("/api/bot/treasury/assets"),
            )
        return {
            "version": VERSION, "exchange_api_version": EXCHANGE_API_VERSION,
            **reconcile_treasury(liabilities, treasury),
        }
    except (ExchangeAPIError, ExchangeContractError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/v0/exchange/users/{user_id}/investigation")
async def exchange_user_investigation(
    user_id: int,
    days: int = Query(default=30, ge=1, le=366),
    limit: int = Query(default=50, ge=1, le=100),
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    authorize("view_user_investigation", role)
    if user_id < 1:
        raise HTTPException(status_code=422, detail="user_id must be positive")
    now = datetime.now(UTC)
    period = {"date_from": (now - timedelta(days=days)).date().isoformat(), "date_to": now.date().isoformat()}
    try:
        if settings.bitagent_mode == "mock":
            payloads = tuple(mock_data.user_dataset(user_id, kind) for kind in (
                "summary", "balances", "trades", "deposits", "withdrawals", "pnl"
            ))
        else:
            root = f"/api/bot/user/{user_id}"
            results = await asyncio.gather(
                exchange_client.get(f"{root}/summary"),
                exchange_client.get(f"{root}/balances"),
                exchange_client.get(f"{root}/trades", {**period, "limit": limit}),
                exchange_client.get(f"{root}/deposits", {**period, "limit": limit}),
                exchange_client.get(f"{root}/withdrawals", {**period, "limit": limit}),
                exchange_client.get(f"{root}/pnl", period),
                return_exceptions=True,
            )
            names = ("summary", "balances", "trades", "deposits", "withdrawals", "pnl")
            source_errors = {
                name: str(result) for name, result in zip(names, results)
                if isinstance(result, Exception)
            }
            payloads = tuple(
                None if isinstance(result, Exception) else result for result in results
            )
        return {
            "version": VERSION, "exchange_api_version": EXCHANGE_API_VERSION,
            **summarize_user_investigation(
                *payloads,
                source_errors=source_errors if settings.bitagent_mode != "mock" else {},
            ),
        }
    except (ExchangeAPIError, ExchangeContractError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


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
        "release": "XIMA Audited Output Channel",
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


@app.post("/api/v0/marketing/pilot/approvals", status_code=201)
async def pilot_approval(
    request: PilotApprovalRequest,
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    decision = authorize("manage_marketing_automation", role)
    if not decision["allowed"]:
        raise HTTPException(status_code=403, detail={"code": "automation_role_denied"})
    return {"version": VERSION, "approval": create_pilot_approval(settings.evidence_db_path, request)}


@app.post("/api/v0/marketing/pilot/schedules")
async def pilot_schedule(
    request: PilotScheduleRequest,
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    decision = authorize("manage_marketing_automation", role)
    if not decision["allowed"]:
        raise HTTPException(status_code=403, detail={"code": "automation_role_denied"})
    status_code, result = schedule_pilot(settings.evidence_db_path, request)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=result)
    return {"version": VERSION, "schedule": result}


@app.post("/api/v0/marketing/pilot/schedules/{schedule_id}/cancel")
async def pilot_cancel(
    schedule_id: str,
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    decision = authorize("manage_marketing_automation", role)
    if not decision["allowed"]:
        raise HTTPException(status_code=403, detail={"code": "automation_role_denied"})
    status_code, result = cancel_pilot(settings.evidence_db_path, schedule_id)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=result)
    return {"version": VERSION, "schedule": result}


@app.get("/api/v0/marketing/pilot/monitoring")
async def pilot_monitor(
    tenant_id: str = Query(min_length=1, max_length=100),
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    decision = authorize("manage_marketing_automation", role)
    if not decision["allowed"]:
        raise HTTPException(status_code=403, detail={"code": "automation_role_denied"})
    return {"version": VERSION, **pilot_monitoring(settings.evidence_db_path, tenant_id)}


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


@app.post("/api/v0/xima/evidence", status_code=201)
async def xima_evidence_ingest(
    request: EvidenceEnvelope,
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    decision = authorize("ingest_xima_evidence", role)
    if not decision["allowed"]:
        raise HTTPException(status_code=403, detail={"code": "evidence_ingest_denied"})
    status_code, result = ingest_evidence(settings.evidence_db_path, request)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=result)
    return {"version": VERSION, "evidence": result}


@app.get("/api/v0/xima/sources/health")
async def xima_source_health(
    tenant_id: str = Query(min_length=1, max_length=100),
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    authorize("view_xima", role)
    return {"version": VERSION, **source_health(settings.evidence_db_path, tenant_id)}


@app.get("/api/v0/xima/evidence/{evidence_id}/replay")
async def xima_evidence_replay(
    evidence_id: str,
    tenant_id: str = Query(min_length=1, max_length=100),
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    decision = authorize("ingest_xima_evidence", role)
    if not decision["allowed"]:
        raise HTTPException(status_code=403, detail={"code": "evidence_replay_denied"})
    status_code, result = replay_evidence(settings.evidence_db_path, tenant_id, evidence_id)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=result)
    return {"version": VERSION, "evidence": result}


@app.get("/api/v0/xima/audit/verify")
async def xima_audit_verify(
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    authorize("view_audit", role)
    return {"version": VERSION, **verify_xima_chain(settings.evidence_db_path)}


@app.post("/api/v0/xima/agents/operations/analyze")
async def xima_operations_analyze(
    request: OperationsAnalysisRequest,
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    authorize("view_xima", role)
    analysis = analyze_operations(request)
    analysis["audit"] = record_xima_output(
        settings.evidence_db_path, request.tenant_id, "operations_analysis",
        analysis.get("incident_key", request.observed_at.isoformat()), analysis,
    )
    return {"version": VERSION, "analysis": analysis}


@app.post("/api/v0/xima/agents/market-risk/analyze")
async def xima_market_risk_analyze(
    request: XimaMarketRiskRequest,
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    authorize("view_xima", role)
    analysis = analyze_xima_market_risk(request)
    analysis["audit"] = record_xima_output(
        settings.evidence_db_path, request.tenant_id, "market_risk_analysis",
        request.market, analysis,
    )
    return {"version": VERSION, "analysis": analysis}


@app.post("/api/v0/xima/agents/treasury/analyze")
async def xima_treasury_analyze(
    request: TreasuryAnalysisRequest,
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    authorize("view_xima", role)
    analysis = analyze_treasury(request)
    analysis["audit"] = record_xima_output(
        settings.evidence_db_path, request.tenant_id, "treasury_analysis",
        request.observed_at.isoformat(), analysis,
    )
    return {"version": VERSION, "analysis": analysis}


@app.post("/api/v0/xima/agents/aml-fraud/analyze")
async def xima_aml_analyze(
    request: AMLAnalysisRequest,
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    authorize("view_xima", role)
    analysis = analyze_aml(request)
    analysis["audit"] = record_xima_output(
        settings.evidence_db_path, request.tenant_id, "aml_fraud_analysis",
        request.observed_at.isoformat(), analysis,
    )
    return {"version": VERSION, "analysis": analysis}


@app.post("/api/v0/xima/agents/aml-fraud/feedback", status_code=201)
async def xima_aml_feedback(
    request: AMLFeedbackRequest,
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    decision = authorize("submit_feedback", role)
    if not decision["allowed"]:
        raise HTTPException(status_code=403, detail={"code": "feedback_role_denied"})
    return {"version": VERSION, "feedback": record_aml_feedback(settings.evidence_db_path, request)}


@app.post("/api/v0/xima/agents/security/analyze")
async def xima_security_analyze(
    request: SecurityAnalysisRequest,
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    authorize("view_xima", role)
    analysis = analyze_security(request)
    analysis["audit"] = record_xima_output(
        settings.evidence_db_path, request.tenant_id, "security_analysis",
        request.observed_at.isoformat(), analysis,
    )
    return {"version": VERSION, "analysis": analysis}


@app.post("/api/v0/xima/knowledge/documents", status_code=201)
async def xima_knowledge_ingest(
    request: KnowledgeDocumentRequest,
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    decision = authorize("manage_xima_knowledge", role)
    if not decision["allowed"]:
        raise HTTPException(status_code=403, detail={"code": "knowledge_role_denied"})
    status_code, result = ingest_knowledge(settings.evidence_db_path, request)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=result)
    return {"version": VERSION, "document": result}


@app.post("/api/v0/xima/knowledge/documents/upload", status_code=201)
async def xima_knowledge_upload(
    request: KnowledgeUploadRequest,
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    decision = authorize("manage_xima_knowledge", role)
    if not decision["allowed"]:
        raise HTTPException(status_code=403, detail={"code": "knowledge_role_denied"})
    try:
        content, processing = extract_document_text(request.filename, request.content_base64)
        document = KnowledgeDocumentRequest(**request.document.model_dump(), content=content)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "document_processing_failed",
                                                     "message": str(exc)}) from exc
    status_code, result = ingest_knowledge(settings.evidence_db_path, document)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=result)
    return {"version": VERSION, "document": result, "processing": processing}


@app.get("/api/v0/xima/knowledge/documents")
async def xima_knowledge_inventory(
    tenant_id: str = Query(min_length=1, max_length=100),
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    decision = authorize("view_xima", role)
    items = list_knowledge(settings.evidence_db_path, tenant_id, decision["role"])
    return {"version": VERSION, "tenant_id": tenant_id, "items": items,
            "count": len(items), "action_executed": False}


@app.post("/api/v0/xima/knowledge/documents/{document_id}/versions/{document_version}/status")
async def xima_knowledge_status(
    document_id: str, document_version: str, request: KnowledgeStatusRequest,
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    decision = authorize("manage_xima_knowledge", role)
    if not decision["allowed"]:
        raise HTTPException(status_code=403, detail={"code": "knowledge_role_denied"})
    status_code, result = change_knowledge_status(
        settings.evidence_db_path, document_id, document_version, request
    )
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=result)
    return {"version": VERSION, "transition": result}


@app.get("/api/v0/xima/knowledge/search")
async def xima_knowledge_search(
    tenant_id: str = Query(min_length=1, max_length=100),
    query: str = Query(min_length=2, max_length=1000),
    limit: int = Query(default=5, ge=1, le=20),
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    decision = authorize("view_xima", role)
    return {"version": VERSION, "tenant_id": tenant_id,
            "items": retrieve_knowledge(settings.evidence_db_path, tenant_id, decision["role"], query, limit)}


@app.post("/api/v0/xima/knowledge/qa")
async def xima_knowledge_qa(
    request: KnowledgeQuestionRequest,
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    decision = authorize("view_xima", role)
    return {"version": VERSION, "tenant_id": request.tenant_id,
            "result": answer_knowledge_question(
                settings.evidence_db_path, request, decision["role"])}


@app.post("/api/v0/xima/knowledge/evaluations")
async def xima_knowledge_evaluation(
    request: KnowledgeEvaluationRequest,
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    decision = authorize("view_xima", role)
    result = evaluate_knowledge(settings.evidence_db_path, request, decision["role"])
    result["audit"] = record_xima_output(
        settings.evidence_db_path, request.tenant_id, "knowledge_evaluation",
        datetime.now(UTC).isoformat(), result,
    )
    return {"version": VERSION, "tenant_id": request.tenant_id, "evaluation": result}


@app.post("/api/v0/xima/agents/support/analyze")
async def xima_support_analyze(
    request: SupportTicketRequest,
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    decision = authorize("view_xima", role)
    analysis = analyze_support(settings.evidence_db_path, request, decision["role"])
    analysis["audit"] = record_xima_output(
        settings.evidence_db_path, request.tenant_id, "support_analysis",
        request.ticket_id, analysis,
    )
    return {"version": VERSION, "analysis": analysis}


@app.post("/api/v0/xima/governance/policy/evaluate")
async def xima_policy_evaluate(
    request: XimaPolicyRequest,
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    authorize("view_xima", role)
    result = evaluate_xima_policy(request)
    result["audit"] = record_xima_output(
        settings.evidence_db_path, request.tenant_id, "policy_decision",
        request.action, result,
    )
    return {"version": VERSION, "result": result}


@app.post("/api/v0/xima/governance/registry", status_code=201)
async def xima_registry_create(
    request: RegistryEntryRequest,
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    decision = authorize("manage_xima_governance", role)
    if not decision["allowed"]:
        raise HTTPException(status_code=403, detail={"code": "governance_role_denied"})
    status_code, result = register_component(settings.evidence_db_path, request)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=result)
    return {"version": VERSION, "entry": result}


@app.post("/api/v0/xima/governance/evaluations")
async def xima_evaluation(
    request: XimaEvaluationRequest,
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    authorize("view_xima", role)
    evaluation = evaluate_quality(request)
    evaluation["audit"] = record_xima_output(
        settings.evidence_db_path, request.tenant_id, "quality_evaluation",
        request.component_name, evaluation,
    )
    return {"version": VERSION, "evaluation": evaluation}


@app.post("/api/v0/xima/pilot/shadow/evaluate")
async def xima_shadow_evaluate(
    request: ShadowPilotRequest,
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    authorize("view_xima", role)
    evaluation = evaluate_shadow_pilot(request)
    evaluation["audit"] = record_xima_output(
        settings.evidence_db_path, request.tenant_id, "shadow_pilot_evaluation",
        request.window_end.isoformat(), evaluation,
    )
    return {"version": VERSION, "evaluation": evaluation}


def authorize_xima_actions(role: str | None) -> None:
    decision = authorize("manage_xima_actions", role)
    if not decision["allowed"]:
        raise HTTPException(status_code=403, detail={"code": "action_role_denied"})


@app.post("/api/v0/xima/actions/previews", status_code=201)
async def xima_action_preview(
    request: ActionPreviewRequest,
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    authorize_xima_actions(role)
    return {"version": VERSION, "preview": create_preview(settings.evidence_db_path, request)}


@app.post("/api/v0/xima/actions/authorizations", status_code=201)
async def xima_action_authorization(
    request: ActionAuthorizationRequest,
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    authorize_xima_actions(role)
    status_code, result = authorize_preview(settings.evidence_db_path, request)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=result)
    return {"version": VERSION, "authorization": result}


@app.post("/api/v0/xima/actions/executions", status_code=201)
async def xima_action_execute(
    request: ActionExecutionRequest,
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    authorize_xima_actions(role)
    status_code, result = execute_action(settings.evidence_db_path, request)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=result)
    return {"version": VERSION, "execution": result}


@app.post("/api/v0/xima/actions/executions/{execution_id}/rollback")
async def xima_action_rollback(
    execution_id: str,
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    authorize_xima_actions(role)
    status_code, result = rollback_action(settings.evidence_db_path, execution_id)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=result)
    return {"version": VERSION, "execution": result}


@app.post("/api/v0/xima/actions/kill-switch")
async def xima_action_kill_switch(
    paused: bool,
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    authorize_xima_actions(role)
    return {"version": VERSION, **set_kill_switch(settings.evidence_db_path, paused)}


@app.post("/api/v0/xima/agents/executive/brief")
async def xima_executive_brief(
    request: ExecutiveBriefRequest,
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    authorize("view_xima", role)
    brief = build_executive_brief(request)
    brief["audit"] = record_xima_output(
        settings.evidence_db_path, request.tenant_id, "executive_brief",
        request.reporting_period, brief,
    )
    return {"version": VERSION, "brief": brief}


@app.get("/api/v0/xima/integrations/exchange/health")
async def xima_exchange_integration_health(
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    authorize("view_xima", role)
    return {"version": VERSION, "source_id": "exchange-api",
            "health": exchange_client.health_snapshot()}


@app.get("/api/v0/xima/outputs/recent")
async def xima_outputs_recent(
    tenant_id: str = Query(min_length=1, max_length=100),
    limit: int = Query(default=50, ge=1, le=500),
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    authorize("view_xima", role)
    return {"version": VERSION, "tenant_id": tenant_id,
            "items": recent_xima_outputs(settings.evidence_db_path, tenant_id, limit)}


@app.get("/api/v0/xima/outputs/audit/verify")
async def xima_outputs_verify(
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    authorize("view_audit", role)
    return {"version": VERSION, **verify_xima_output_chain(settings.evidence_db_path)}


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
    agent: Literal[
        "operations", "market-risk", "treasury", "aml-fraud",
        "security", "support", "executive", "governance",
    ] = "operations"

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
    agent_domain = request.agent
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
            agent_domain=agent_domain,
        )
        return {
            "version": VERSION,
            "agent": agent_domain,
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
            agent_domain=agent_domain,
        )
        return {
            "version": VERSION,
            "agent": agent_domain,
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
            agent_domain=agent_domain,
        )
        return {
            "version": VERSION,
            "agent": agent_domain,
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
                agent_domain=agent_domain,
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
            agent_domain=agent_domain,
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
        agent_domain=agent_domain,
    )
    return {
        "version": VERSION,
        "agent": agent_domain,
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
