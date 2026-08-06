from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field, model_validator


ToolMode = Literal["read", "controlled_write"]
RiskClass = Literal["none", "low", "medium", "high", "prohibited"]
ApprovalPolicy = Literal["none", "explicit_confirmation", "single_approval", "maker_checker", "quorum", "prohibited"]


class ToolFieldContract(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    type: Literal["string", "integer", "number", "boolean", "datetime", "object", "array"]
    required: bool = True
    minimum: float | None = None
    maximum: float | None = None
    enum: list[str] = Field(default_factory=list, max_length=100)
    pattern: str | None = Field(default=None, max_length=500)
    description: str = Field(min_length=3, max_length=500)


class ExchangeToolContract(BaseModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,149}$")
    version: str = Field(min_length=1, max_length=50)
    mode: ToolMode
    description: str = Field(min_length=3, max_length=1000)
    risk: RiskClass
    required_roles: list[str] = Field(min_length=1, max_length=50)
    fields: list[ToolFieldContract] = Field(default_factory=list, max_length=100)
    approval_policy: ApprovalPolicy = "none"
    reversible: bool = False
    idempotent: bool = True
    verification_path: str = Field(min_length=1, max_length=300)
    execution_path: str | None = Field(default=None, max_length=300)
    allowed_environments: list[Literal["development", "test", "staging", "pilot", "production"]] = Field(min_length=1)
    rate_limit_per_minute: int = Field(ge=1, le=10000)
    timeout_seconds: int = Field(ge=1, le=120)
    contract_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def validate_control_boundaries(self):
        if self.mode == "controlled_write":
            if not self.execution_path:
                raise ValueError("controlled write tool requires execution_path")
            if self.approval_policy in {"none", "prohibited"}:
                raise ValueError("controlled write tool requires an approval policy")
            if not self.idempotent:
                raise ValueError("controlled write tool must support idempotency")
        if self.mode == "read" and self.approval_policy not in {"none", "explicit_confirmation"}:
            raise ValueError("read tool cannot require write approval policy")
        if self.risk == "prohibited" and self.mode != "controlled_write":
            raise ValueError("prohibited tools must not be exposed as read tools")
        return self

    def calculated_hash(self) -> str:
        payload = self.model_dump(exclude={"contract_hash"})
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


class CapabilityEnvelope(BaseModel):
    api_version: str = Field(min_length=1, max_length=50)
    tenant_id: str = Field(min_length=1, max_length=100)
    observed_at: AwareDatetime
    generated_at: AwareDatetime
    source: str = Field(min_length=2, max_length=100)
    fresh: bool
    partial: bool
    limitations: list[str] = Field(default_factory=list, max_length=100)
    tools: list[ExchangeToolContract] = Field(default_factory=list, max_length=500)
    signature_key_id: str = Field(min_length=2, max_length=100)
    envelope_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def validate_envelope(self):
        if self.partial and not self.limitations:
            raise ValueError("partial capability envelope requires limitations")
        if self.generated_at < self.observed_at:
            raise ValueError("generated_at cannot precede observed_at")
        names = [tool.name for tool in self.tools]
        if len(names) != len(set(names)):
            raise ValueError("duplicate tool names are not allowed")
        for tool in self.tools:
            if tool.contract_hash and tool.contract_hash != tool.calculated_hash():
                raise ValueError(f"contract hash mismatch for {tool.name}")
        return self

    def calculated_hash(self) -> str:
        payload = self.model_dump(mode="json", exclude={"envelope_hash"})
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


class IdentityClaims(BaseModel):
    subject: str = Field(min_length=1, max_length=150)
    tenant_id: str = Field(min_length=1, max_length=100)
    roles: list[str] = Field(min_length=1, max_length=100)
    scopes: list[str] = Field(default_factory=list, max_length=200)
    authentication_strength: Literal["password", "mfa", "phishing_resistant_mfa"]
    authorization_id: str = Field(min_length=3, max_length=150)
    delegated_by: str | None = Field(default=None, max_length=150)
    issued_at: AwareDatetime
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def validate_lifetime(self):
        if self.expires_at <= self.issued_at:
            raise ValueError("identity claims must expire after issuance")
        return self


def validate_capability_envelope(envelope: CapabilityEnvelope, *, expected_tenant: str) -> dict:
    failures: list[str] = []
    if envelope.tenant_id != expected_tenant:
        failures.append("tenant_mismatch")
    if not envelope.fresh:
        failures.append("stale_capability_contract")
    if envelope.envelope_hash and envelope.envelope_hash != envelope.calculated_hash():
        failures.append("envelope_hash_mismatch")
    prohibited_patterns = (
        "shell", "sql.execute", "http.proxy", "wallet.sign", "balance.set", "private_key", "seed_phrase"
    )
    for tool in envelope.tools:
        normalized = tool.name.lower()
        if any(pattern in normalized for pattern in prohibited_patterns):
            failures.append(f"prohibited_tool:{tool.name}")
        if tool.mode == "controlled_write" and "production" in tool.allowed_environments:
            if tool.risk == "high" and tool.approval_policy not in {"maker_checker", "quorum"}:
                failures.append(f"insufficient_production_approval:{tool.name}")
    return {
        "valid": not failures,
        "failures": failures,
        "tool_count": len(envelope.tools),
        "read_tools": sum(tool.mode == "read" for tool in envelope.tools),
        "controlled_write_tools": sum(tool.mode == "controlled_write" for tool in envelope.tools),
        "action_executed": False,
    }
