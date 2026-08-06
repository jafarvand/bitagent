from app.command_receipts import CommandReceipt, append_receipt, get_receipt, verified_status, verify_receipt_chain


def _receipt(command_id: str) -> CommandReceipt:
    return CommandReceipt(
        command_id=command_id,
        session_id="session-1",
        tenant_id="tenant-a",
        user_id="manager-1",
        intent="calculate",
        tool_name="management.calculate_report",
        status="succeeded",
        requested_at="2026-08-06T10:00:00+00:00",
        executed_at="2026-08-06T10:00:01+00:00",
        verified_at="2026-08-06T10:00:02+00:00",
        source_system_status="complete",
        evidence_refs=["snapshot:1"],
        action_executed=False,
    )


def test_receipts_are_idempotent_and_tenant_scoped(tmp_path):
    path = str(tmp_path / "receipts.sqlite3")
    first = append_receipt(path, _receipt("CMD-1"))
    second = append_receipt(path, _receipt("CMD-1"))
    assert first["replayed"] is False
    assert second["replayed"] is True
    assert get_receipt(path, command_id="CMD-1", tenant_id="tenant-a") is not None
    assert get_receipt(path, command_id="CMD-1", tenant_id="tenant-b") is None


def test_receipt_chain_verifies(tmp_path):
    path = str(tmp_path / "receipts.sqlite3")
    append_receipt(path, _receipt("CMD-1"))
    append_receipt(path, _receipt("CMD-2"))
    result = verify_receipt_chain(path)
    assert result["valid"] is True
    assert result["records"] == 2


def test_success_without_source_verification_is_pending():
    assert verified_status(
        requested_status="succeeded",
        source_verified=False,
        source_system_status=None,
    ) == "pending_verification"
