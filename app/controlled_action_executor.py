from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from pydantic import BaseModel, Field

from app.exchange_command_contracts import ExchangeToolContract, IdentityClaims


class ApprovalEvidence(BaseModel):
    approval_ids: list[str] = Field(min_length=1, max_length=20)
    approval_policy: str
    plan_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    approved: bool
    expires_at: str
    approver_ids: list[str] = Field(min_length=1, max_length=20)


class ControlledActionRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=100)
    session_id: str = Field(min_length=3, max_length=100)
    command_id: str = Field(min_length=3, max_length=100)
    tool_name: str = Field(min_length=3, max_length=150)
    arguments: dict = Field(min_length=1)
    plan_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    idempotency_key: str = Field(min_length=8, max_length=100)
    environment: str = Field(pattern=r"^(development|test|staging|pilot|production)$")
    expected_state_version: str = Field(min_length=1, max_length=200)
    rollback_requested_on_failure: bool = True


class ActionTransport(Protocol):
    def execute(
        self,
        *,
        contract: ExchangeToolContract,
        request: ControlledActionRequest,
        identity: IdentityClaims,
        approval: ApprovalEvidence,
    ) -> dict: ...

    def verify(
        self,
        *,
        contract: ExchangeToolContract,
        request: ControlledActionRequest,
        execution_result: dict,
    ) -> dict: ...

    def rollback(
        self,
        *,
        contract: ExchangeToolContract,
        request: ControlledActionRequest,
        execution_result: dict,
    ) -> dict: ...


@dataclass(frozen=True)
class ControlledActionExecutor:
    transport: ActionTransport

    def execute(
        self,
        *,
        contract: ExchangeToolContract,
        request: ControlledActionRequest,
        identity: IdentityClaims,
        approval: ApprovalEvidence,
    ) -> dict:
        blocked = self._preflight(
            contract=contract,
            request=request,
            identity=identity,
            approval=approval,
        )
        if blocked:
            return self._receipt(
                request=request,
                status="blocked",
                limitations=blocked,
                action_executed=False,
            )

        started_at = datetime.now(UTC)
        try:
            execution = self.transport.execute(
                contract=contract,
                request=request,
                identity=identity,
                approval=approval,
            )
        except Exception as exc:
            return self._receipt(
                request=request,
                status="failed",
                limitations=[f"execution transport failed: {type(exc).__name__}"],
                action_executed=False,
                started_at=started_at,
            )

        verification = self.transport.verify(
            contract=contract,
            request=request,
            execution_result=execution,
        )
        if verification.get("passed") is True:
            return self._receipt(
                request=request,
                status="succeeded",
                limitations=[],
                action_executed=True,
                started_at=started_at,
                execution=execution,
                verification=verification,
            )

        rollback = None
        if request.rollback_requested_on_failure and contract.reversible:
            rollback = self.transport.rollback(
                contract=contract,
                request=request,
                execution_result=execution,
            )
        status = "rolled_back" if rollback and rollback.get("passed") is True else "pending_verification"
        return self._receipt(
            request=request,
            status=status,
            limitations=["source-system verification did not pass"],
            action_executed=True,
            started_at=started_at,
            execution=execution,
            verification=verification,
            rollback=rollback,
        )

    @staticmethod
    def _preflight(
        *,
        contract: ExchangeToolContract,
        request: ControlledActionRequest,
        identity: IdentityClaims,
        approval: ApprovalEvidence,
    ) -> list[str]:
        failures: list[str] = []
        now = datetime.now(UTC)
        if contract.name != request.tool_name:
            failures.append("tool_contract_mismatch")
        if contract.mode != "controlled_write":
            failures.append("tool_is_not_controlled_write")
        if request.tenant_id != identity.tenant_id:
            failures.append("identity_tenant_mismatch")
        if request.environment not in contract.allowed_environments:
            failures.append("environment_not_allowed")
        if not set(identity.roles) & set(contract.required_roles):
            failures.append("role_not_authorized")
        if identity.expires_at <= now:
            failures.append("identity_expired")
        if contract.risk in {"medium", "high"} and identity.authentication_strength == "password":
            failures.append("mfa_required")
        if not approval.approved:
            failures.append("approval_not_granted")
        if approval.plan_hash != request.plan_hash:
            failures.append("approval_plan_hash_mismatch")
        if approval.approval_policy != contract.approval_policy:
            failures.append("approval_policy_mismatch")
        try:
            approval_expiry = datetime.fromisoformat(approval.expires_at)
        except ValueError:
            failures.append("approval_expiry_invalid")
        else:
            if approval_expiry <= now:
                failures.append("approval_expired")
        if contract.approval_policy == "maker_checker" and identity.subject in approval.approver_ids:
            failures.append("requester_cannot_be_checker")
        missing = [field.name for field in contract.fields if field.required and field.name not in request.arguments]
        if missing:
            failures.append(f"missing_fields:{','.join(missing)}")
        return failures

    @staticmethod
    def _receipt(
        *,
        request: ControlledActionRequest,
        status: str,
        limitations: list[str],
        action_executed: bool,
        started_at: datetime | None = None,
        execution: dict | None = None,
        verification: dict | None = None,
        rollback: dict | None = None,
    ) -> dict:
        payload = {
            "execution_id": execution.get("execution_id") if execution else None,
            "command_id": request.command_id,
            "session_id": request.session_id,
            "tool": request.tool_name,
            "status": status,
            "started_at": (started_at or datetime.now(UTC)).isoformat(),
            "completed_at": datetime.now(UTC).isoformat(),
            "idempotency_key": request.idempotency_key,
            "expected_state_version": request.expected_state_version,
            "execution": execution,
            "verification": verification,
            "rollback": rollback,
            "limitations": limitations,
            "action_executed": action_executed,
        }
        payload["receipt_hash"] = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
        ).hexdigest()
        return payload
