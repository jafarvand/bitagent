import hashlib
import json

from app.command_approvals import (
    ApprovalDecision,
    ApprovalRequestCreate,
    create_approval,
    decide_approval,
    get_approval,
    list_pending,
)


def _plan_hash() -> str:
    return hashlib.sha256(json.dumps({"tool": "settings.propose"}, sort_keys=True).encode()).hexdigest()


def test_maker_checker_blocks_self_approval(tmp_path):
    path = str(tmp_path / "approvals.sqlite3")
    created = create_approval(
        path,
        ApprovalRequestCreate(
            tenant_id="tenant-a",
            tool_name="settings.propose",
            requester_id="manager-1",
            requester_role="manager",
            arguments={"setting_name": "threshold", "new_value": "5"},
            risk="high",
            approval_policy="maker_checker",
            reason="policy update",
            plan_hash=_plan_hash(),
        ),
    )
    result = decide_approval(
        path,
        request_id=created["request_id"],
        tenant_id="tenant-a",
        decision=ApprovalDecision(
            approver_id="manager-1",
            approver_role="manager",
            decision="approve",
            reason="approved",
            expected_version=1,
            idempotency_key="idem-self-approval",
        ),
    )
    assert result["code"] == "maker_checker_separation_required"


def test_authorized_checker_can_approve_and_replay_idempotently(tmp_path):
    path = str(tmp_path / "approvals.sqlite3")
    created = create_approval(
        path,
        ApprovalRequestCreate(
            tenant_id="tenant-a",
            tool_name="settings.propose",
            requester_id="manager-1",
            requester_role="manager",
            arguments={"setting_name": "threshold", "new_value": "5"},
            risk="high",
            approval_policy="maker_checker",
            reason="policy update",
            plan_hash=_plan_hash(),
        ),
    )
    decision = ApprovalDecision(
        approver_id="risk-1",
        approver_role="risk",
        decision="approve",
        reason="risk evidence reviewed",
        expected_version=1,
        idempotency_key="idem-risk-approval",
    )
    first = decide_approval(
        path,
        request_id=created["request_id"],
        tenant_id="tenant-a",
        decision=decision,
    )
    assert first["status"] == "approved"
    assert first["action_executed"] is False
    second = decide_approval(
        path,
        request_id=created["request_id"],
        tenant_id="tenant-a",
        decision=decision,
    )
    assert second["replayed"] is True


def test_pending_list_is_tenant_scoped(tmp_path):
    path = str(tmp_path / "approvals.sqlite3")
    create_approval(
        path,
        ApprovalRequestCreate(
            tenant_id="tenant-a",
            tool_name="workflow.approve",
            requester_id="operator-1",
            requester_role="operator",
            arguments={"request_id": "REQ-1"},
            risk="medium",
            approval_policy="single_approval",
            reason="review complete",
            plan_hash=_plan_hash(),
        ),
    )
    assert len(list_pending(path, tenant_id="tenant-a")) == 1
    assert list_pending(path, tenant_id="tenant-b") == []
