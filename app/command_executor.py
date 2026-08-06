from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Callable
from uuid import uuid4

from pydantic import BaseModel, Field

from app.chat_commands import TOOL_REGISTRY


class ReadOnlyToolResult(BaseModel):
    status: str = Field(pattern=r"^(succeeded|partial|blocked|failed)$")
    data: dict = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    observed_at: str | None = None
    limitations: list[str] = Field(default_factory=list)
    verification: dict = Field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionContext:
    tenant_id: str
    user_id: str
    role: str
    session_id: str
    command_id: str


ToolHandler = Callable[[ExecutionContext, dict], ReadOnlyToolResult]


class ReadOnlyToolExecutor:
    def __init__(self) -> None:
        self._handlers: dict[str, ToolHandler] = {}

    def register(self, tool_name: str, handler: ToolHandler) -> None:
        definition = TOOL_REGISTRY.get(tool_name)
        if not definition:
            raise KeyError("unknown_tool")
        if definition.exchange_write_required:
            raise ValueError("write_tool_cannot_be_registered_as_readonly")
        self._handlers[tool_name] = handler

    def execute(
        self,
        *,
        tool_name: str,
        arguments: dict,
        tenant_id: str,
        user_id: str,
        role: str,
        session_id: str,
        command_id: str | None = None,
    ) -> dict:
        definition = TOOL_REGISTRY.get(tool_name)
        if not definition:
            return self._blocked_receipt(
                tool_name=tool_name,
                session_id=session_id,
                command_id=command_id,
                reason="unknown_tool",
            )
        if definition.exchange_write_required:
            return self._blocked_receipt(
                tool_name=tool_name,
                session_id=session_id,
                command_id=command_id,
                reason="write_tool_requires_approval_gateway",
            )
        if role not in definition.required_roles:
            return self._blocked_receipt(
                tool_name=tool_name,
                session_id=session_id,
                command_id=command_id,
                reason="role_not_authorized",
            )
        missing = [field for field in definition.required_fields if not arguments.get(field)]
        if missing:
            return self._blocked_receipt(
                tool_name=tool_name,
                session_id=session_id,
                command_id=command_id,
                reason=f"missing_fields:{','.join(missing)}",
            )
        handler = self._handlers.get(tool_name)
        if not handler:
            return self._blocked_receipt(
                tool_name=tool_name,
                session_id=session_id,
                command_id=command_id,
                reason="tool_handler_unavailable",
            )

        resolved_command_id = command_id or str(uuid4())
        started_at = datetime.now(UTC)
        context = ExecutionContext(
            tenant_id=tenant_id,
            user_id=user_id,
            role=role,
            session_id=session_id,
            command_id=resolved_command_id,
        )
        try:
            result = handler(context, arguments)
        except Exception as exc:  # handler errors must not be represented as success
            return self._receipt(
                command_id=resolved_command_id,
                session_id=session_id,
                tool_name=tool_name,
                status="failed",
                started_at=started_at,
                result=None,
                limitations=[f"tool execution failed: {type(exc).__name__}"],
                verified=False,
            )

        verified, verification_reason = self._verify(result)
        status = result.status
        if status == "succeeded" and not verified:
            status = "partial"
            result.limitations.append(verification_reason)
        return self._receipt(
            command_id=resolved_command_id,
            session_id=session_id,
            tool_name=tool_name,
            status=status,
            started_at=started_at,
            result=result,
            limitations=result.limitations,
            verified=verified,
        )

    @staticmethod
    def _verify(result: ReadOnlyToolResult) -> tuple[bool, str]:
        if result.status not in {"succeeded", "partial"}:
            return False, "non-success result"
        if not result.observed_at:
            return False, "missing observation timestamp"
        if not result.evidence_refs:
            return False, "missing evidence references"
        if result.verification.get("passed") is not True:
            return False, "source verification did not pass"
        return True, "verified"

    def _blocked_receipt(
        self,
        *,
        tool_name: str,
        session_id: str,
        command_id: str | None,
        reason: str,
    ) -> dict:
        return self._receipt(
            command_id=command_id or str(uuid4()),
            session_id=session_id,
            tool_name=tool_name,
            status="blocked",
            started_at=datetime.now(UTC),
            result=None,
            limitations=[reason],
            verified=False,
        )

    @staticmethod
    def _receipt(
        *,
        command_id: str,
        session_id: str,
        tool_name: str,
        status: str,
        started_at: datetime,
        result: ReadOnlyToolResult | None,
        limitations: list[str],
        verified: bool,
    ) -> dict:
        completed_at = datetime.now(UTC)
        payload = {
            "command_id": command_id,
            "session_id": session_id,
            "tool": tool_name,
            "status": status,
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
            "verified": verified,
            "result": result.model_dump() if result else None,
            "limitations": limitations,
            "action_executed": False,
        }
        payload["receipt_hash"] = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return payload
