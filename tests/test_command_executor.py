from datetime import UTC, datetime

from app.command_executor import ReadOnlyToolExecutor, ReadOnlyToolResult


def _verified_handler(context, arguments):
    return ReadOnlyToolResult(
        status="succeeded",
        data={"report_type": arguments["report_type"], "value": "108.4%"},
        evidence_refs=["snapshot:treasury-1", "snapshot:liabilities-1"],
        observed_at=datetime.now(UTC).isoformat(),
        verification={"passed": True, "method": "source_snapshot_reconciliation"},
    )


def test_verified_readonly_tool_returns_success_receipt():
    executor = ReadOnlyToolExecutor()
    executor.register("management.calculate_report", _verified_handler)
    receipt = executor.execute(
        tool_name="management.calculate_report",
        arguments={"report_type": "treasury coverage", "period": "today"},
        tenant_id="tenant-a",
        user_id="manager-1",
        role="manager",
        session_id="session-1",
    )
    assert receipt["status"] == "succeeded"
    assert receipt["verified"] is True
    assert receipt["action_executed"] is False
    assert len(receipt["receipt_hash"]) == 64


def test_write_tool_is_never_executed_by_readonly_executor():
    executor = ReadOnlyToolExecutor()
    receipt = executor.execute(
        tool_name="workflow.approve",
        arguments={"request_id": "REQ-1", "reason": "reviewed"},
        tenant_id="tenant-a",
        user_id="manager-1",
        role="manager",
        session_id="session-1",
    )
    assert receipt["status"] == "blocked"
    assert "write_tool_requires_approval_gateway" in receipt["limitations"]


def test_missing_verification_downgrades_success_to_partial():
    executor = ReadOnlyToolExecutor()

    def unverified(context, arguments):
        return ReadOnlyToolResult(
            status="succeeded",
            data={"items": 3},
            evidence_refs=["source:1"],
            observed_at=datetime.now(UTC).isoformat(),
            verification={"passed": False},
        )

    executor.register("management.search", unverified)
    receipt = executor.execute(
        tool_name="management.search",
        arguments={"query": "pending incidents"},
        tenant_id="tenant-a",
        user_id="operator-1",
        role="operator",
        session_id="session-2",
    )
    assert receipt["status"] == "partial"
    assert receipt["verified"] is False
