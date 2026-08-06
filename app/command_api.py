from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app.chat_commands import CommandState, TOOL_REGISTRY, plan_command
from app.command_sessions import cancel_session, create_session, load_session, save_state
from app.config import settings
from app.management_questions import question_catalog, readiness_summary


router = APIRouter(prefix="/api/v0/commands", tags=["chat commands"])


class SessionCreateRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=100)
    user_id: str = Field(min_length=1, max_length=100)
    ttl_minutes: int = Field(default=30, ge=1, le=1440)


class CommandMessageRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=100)
    user_id: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=4000)
    expected_state_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class CommandCancelRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=100)
    user_id: str = Field(min_length=1, max_length=100)
    expected_state_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


def _role(role: str | None) -> str:
    return (role or "viewer").strip().lower()


def _db_path() -> str:
    return settings.evidence_db_path


@router.get("/tools")
def command_tools(role: str | None = Header(default=None, alias="X-BitAgent-Role")):
    current_role = _role(role)
    tools = []
    for tool in TOOL_REGISTRY.values():
        tools.append({
            **tool.model_dump(),
            "authorized": current_role in tool.required_roles,
        })
    return {
        "tools": tools,
        "count": len(tools),
        "role": current_role,
        "action_executed": False,
    }


@router.get("/management/questions")
def management_questions(domain: str | None = None, coverage: str | None = None):
    if coverage not in {None, "supported", "partial", "blocked"}:
        raise HTTPException(status_code=422, detail="invalid coverage")
    return {
        "questions": question_catalog(domain=domain, coverage=coverage),
        "readiness": readiness_summary(),
        "action_executed": False,
    }


@router.post("/sessions", status_code=201)
def start_command_session(
    request: SessionCreateRequest,
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    return create_session(
        _db_path(),
        tenant_id=request.tenant_id,
        user_id=request.user_id,
        role=_role(role),
        ttl_minutes=request.ttl_minutes,
    )


@router.get("/sessions/{session_id}")
def get_command_session(
    session_id: str,
    tenant_id: str,
    user_id: str,
):
    result = load_session(
        _db_path(),
        session_id=session_id,
        tenant_id=tenant_id,
        user_id=user_id,
    )
    if not result:
        raise HTTPException(status_code=404, detail="session not found")
    state: CommandState = result["state"]
    return {
        **{key: value for key, value in result.items() if key != "state"},
        "state": state.model_dump(),
        "action_executed": False,
    }


@router.post("/sessions/{session_id}/messages")
def command_message(
    session_id: str,
    request: CommandMessageRequest,
    role: str | None = Header(default=None, alias="X-BitAgent-Role"),
):
    loaded = load_session(
        _db_path(),
        session_id=session_id,
        tenant_id=request.tenant_id,
        user_id=request.user_id,
    )
    if not loaded:
        raise HTTPException(status_code=404, detail="session not found")
    if loaded["expired"]:
        raise HTTPException(status_code=409, detail="session expired")
    if loaded["state_hash"] != request.expected_state_hash:
        raise HTTPException(status_code=409, detail="session state conflict")
    current_role = _role(role)
    if current_role != loaded["role"]:
        raise HTTPException(status_code=403, detail="session role mismatch")

    planned = plan_command(
        session_id,
        request.message,
        current_role,
        loaded["state"],
    )
    state = CommandState.model_validate(planned["state"])
    persisted = save_state(
        _db_path(),
        tenant_id=request.tenant_id,
        user_id=request.user_id,
        state=state,
        expected_state_hash=request.expected_state_hash,
    )
    return {
        "session_id": session_id,
        "reply": planned["reply"],
        "tool_call": planned["tool_call"],
        "state": persisted["state"],
        "state_hash": persisted["state_hash"],
        "audit": persisted["audit"],
        "action_executed": False,
    }


@router.post("/sessions/{session_id}/cancel")
def cancel_command_session(session_id: str, request: CommandCancelRequest):
    try:
        return cancel_session(
            _db_path(),
            session_id=session_id,
            tenant_id=request.tenant_id,
            user_id=request.user_id,
            expected_state_hash=request.expected_state_hash,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
