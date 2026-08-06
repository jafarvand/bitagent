from datetime import UTC, datetime, timedelta

from app.exchange_command_contracts import (
    CapabilityEnvelope,
    ExchangeToolContract,
    ToolFieldContract,
    validate_capability_envelope,
)


def _read_tool() -> ExchangeToolContract:
    return ExchangeToolContract(
        name="reports.calculate",
        version="1.0.0",
        mode="read",
        description="Calculate a deterministic management report.",
        risk="none",
        required_roles=["manager"],
        fields=[
            ToolFieldContract(
                name="report_type",
                type="string",
                description="Requested deterministic report type.",
            )
        ],
        approval_policy="none",
        reversible=False,
        idempotent=True,
        verification_path="/api/bot/reports/{report_id}",
        allowed_environments=["staging", "pilot", "production"],
        rate_limit_per_minute=60,
        timeout_seconds=10,
    )


def test_valid_read_capability_envelope_passes():
    now = datetime.now(UTC)
    tool = _read_tool()
    envelope = CapabilityEnvelope(
        api_version="0.9.0-pilot",
        tenant_id="tenant-a",
        observed_at=now,
        generated_at=now + timedelta(seconds=1),
        source="exchange-command-registry",
        fresh=True,
        partial=False,
        tools=[tool],
        signature_key_id="exchange-contract-key-1",
    )
    result = validate_capability_envelope(envelope, expected_tenant="tenant-a")
    assert result["valid"] is True
    assert result["read_tools"] == 1


def test_prohibited_generic_tool_is_rejected():
    now = datetime.now(UTC)
    prohibited = ExchangeToolContract(
        name="shell.execute",
        version="1.0.0",
        mode="controlled_write",
        description="Generic shell execution must never be exposed.",
        risk="prohibited",
        required_roles=["admin"],
        fields=[],
        approval_policy="maker_checker",
        reversible=False,
        idempotent=True,
        verification_path="/verify",
        execution_path="/execute",
        allowed_environments=["test"],
        rate_limit_per_minute=1,
        timeout_seconds=5,
    )
    envelope = CapabilityEnvelope(
        api_version="0.9.0-pilot",
        tenant_id="tenant-a",
        observed_at=now,
        generated_at=now,
        source="exchange-command-registry",
        fresh=True,
        partial=False,
        tools=[prohibited],
        signature_key_id="key-1",
    )
    result = validate_capability_envelope(envelope, expected_tenant="tenant-a")
    assert result["valid"] is False
    assert "prohibited_tool:shell.execute" in result["failures"]


def test_stale_or_cross_tenant_contract_fails_closed():
    now = datetime.now(UTC)
    envelope = CapabilityEnvelope(
        api_version="0.9.0-pilot",
        tenant_id="tenant-b",
        observed_at=now,
        generated_at=now,
        source="exchange-command-registry",
        fresh=False,
        partial=False,
        tools=[_read_tool()],
        signature_key_id="key-1",
    )
    result = validate_capability_envelope(envelope, expected_tenant="tenant-a")
    assert result["valid"] is False
    assert "tenant_mismatch" in result["failures"]
    assert "stale_capability_contract" in result["failures"]
