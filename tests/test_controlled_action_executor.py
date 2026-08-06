import hashlib
import json
from datetime import UTC, datetime, timedelta

from app.controlled_action_executor import (
    ApprovalEvidence,
    ControlledActionExecutor,
    ControlledActionRequest,
)
from app.exchange_command_contracts import ExchangeToolContract, IdentityClaims, ToolFieldContract


class FakeTransport:
    def __init__(self, verify_passed=True, rollback_passed=True):
        self.verify_passed = verify_passed
        self.rollback_passed = rollback_passed
        self.executions = 0

    def execute(self, **kwargs):
        self.executions += 1
        return {"execution_id": "EXE-1", "status": "accepted", "state_version": "v2"}

    def verify(self, **kwargs):
        return {"passed": self.verify_passed, "source_status": "paused" if self.verify_passed else "unknown"}

    def rollback(self, **kwargs):
        return {"passed": self.rollback_passed, "source_status": "running"}


def _contract() -> ExchangeToolContract:
    return ExchangeToolContract(
        name="process.pause",
        version="1.0.0",
        mode="controlled_write",
        description="Pause an allowlisted operational process.",
        risk="high",
        required_roles=["manager", "admin"],
        fields=[
            ToolFieldContract(name="process_id", type="string", description="Allowlisted process identifier."),
            ToolFieldContract(name="reason", type="string", description="Documented operational reason."),
        ],
        approval_policy="maker_checker",
        reversible=True,
        idempotent=True,
        verification_path="/api/bot/processes/{process_id}",
        execution_path="/api/bot/processes/{process_id}/pause",
        allowed_environments=["staging", "pilot"],
        rate_limit_per_minute=10,
        timeout_seconds=10,
    )


def _plan_hash() -> str:
    return hashlib.sha256(json.dumps({"tool": "process.pause"}, sort_keys=True).encode()).hexdigest()


def _identity(subject="manager-1") -> IdentityClaims:
    now = datetime.now(UTC)
    return IdentityClaims(
        subject=subject,
        tenant_id="tenant-a",
        roles=["manager"],
        scopes=["process:pause"],
        authentication_strength="mfa",
        authorization_id="AUTH-1",
        issued_at=now,
        expires_at=now + timedelta(minutes=10),
    )


def _approval() -> ApprovalEvidence:
    return ApprovalEvidence(
        approval_ids=["APR-1"],
        approval_policy="maker_checker",
        plan_hash=_plan_hash(),
        approved=True,
        expires_at=(datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
        approver_ids=["risk-1"],
    )


def _request() -> ControlledActionRequest:
    return ControlledActionRequest(
        tenant_id="tenant-a",
        session_id="SES-1",
        command_id="CMD-1",
        tool_name="process.pause",
        arguments={"process_id": "PROC-1", "reason": "incident containment"},
        plan_hash=_plan_hash(),
        idempotency_key="idem-process-pause",
        environment="pilot",
        expected_state_version="v1",
    )


def test_verified_controlled_action_reports_success():
    transport = FakeTransport(verify_passed=True)
    receipt = ControlledActionExecutor(transport).execute(
        contract=_contract(),
        request=_request(),
        identity=_identity(),
        approval=_approval(),
    )
    assert receipt["status"] == "succeeded"
    assert receipt["action_executed"] is True
    assert transport.executions == 1


def test_failed_verification_rolls_back_reversible_action():
    receipt = ControlledActionExecutor(FakeTransport(verify_passed=False, rollback_passed=True)).execute(
        contract=_contract(),
        request=_request(),
        identity=_identity(),
        approval=_approval(),
    )
    assert receipt["status"] == "rolled_back"


def test_missing_mfa_blocks_before_transport():
    now = datetime.now(UTC)
    identity = IdentityClaims(
        subject="manager-1",
        tenant_id="tenant-a",
        roles=["manager"],
        scopes=["process:pause"],
        authentication_strength="password",
        authorization_id="AUTH-1",
        issued_at=now,
        expires_at=now + timedelta(minutes=10),
    )
    transport = FakeTransport()
    receipt = ControlledActionExecutor(transport).execute(
        contract=_contract(),
        request=_request(),
        identity=identity,
        approval=_approval(),
    )
    assert receipt["status"] == "blocked"
    assert "mfa_required" in receipt["limitations"]
    assert transport.executions == 0
