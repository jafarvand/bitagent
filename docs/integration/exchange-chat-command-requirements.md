# Exchange Requirements for Chat-First Commands

**Consumer:** bitAgent Chat-First Command Orchestrator  
**Initial integration mode:** read-only execution and approval planning  
**Controlled writes:** disabled until separately approved and allowlisted

## 1. Required immediately for 2.18.0 read-only commands

The exchange must expose or confirm stable read-only APIs for:

- Searchable operational incidents and status.
- Report inputs with authoritative timestamps and quality metadata.
- Workflow/request lookup by stable ID.
- Current configuration values for settings that may later be changed.
- Actor identity, roles, scopes, and approval authority.
- Post-operation status verification.

Every response must include:

```json
{
  "api_version": "0.9.0-pilot",
  "tenant_id": "exchange-main",
  "observed_at": "2026-08-04T00:00:00Z",
  "generated_at": "2026-08-04T00:00:01Z",
  "fresh": true,
  "partial": false,
  "limitations": [],
  "correlation_id": "corr-...",
  "data": {}
}
```

## 2. Tool and capability discovery

```http
GET /api/bot/commands/capabilities
```

Each tool must declare:

- Stable tool name and version.
- Description.
- Read or write mode.
- Risk class.
- Required roles and scopes.
- Required and optional input fields with types and validation.
- Approval policy: none, explicit confirmation, single approval, maker-checker.
- Reversibility and rollback tool.
- Idempotency support.
- Execution timeout.
- Verification endpoint.
- Environment availability.

Example:

```json
{
  "name": "workflow.approve",
  "version": "1.0",
  "mode": "write",
  "risk": "medium",
  "required_roles": ["aml_supervisor"],
  "required_fields": ["request_id", "reason"],
  "approval_policy": "single_approval",
  "reversible": true,
  "idempotency_required": true,
  "verification_path": "/api/bot/workflows/{request_id}"
}
```

## 3. Workflow and approval APIs

```http
GET  /api/bot/workflows/{request_id}
GET  /api/bot/workflows?status=pending&assignee=me
POST /api/bot/workflows/{request_id}/approve
POST /api/bot/workflows/{request_id}/reject
POST /api/bot/workflows/{request_id}/cancel
```

Write requests must require:

- Signed server-to-server authentication.
- Actor identity and role.
- Exact request version or ETag.
- Reason.
- Idempotency key.
- Correlation ID.
- Short-lived authorization reference when required.

A write response must return:

- Accepted/rejected state.
- Previous and new state.
- Effective timestamp.
- Authoritative actor.
- Audit/event ID.
- Verification link or state version.
- Rollback availability.

## 4. Process-control APIs

Only explicitly allowlisted processes may be controlled.

```http
GET  /api/bot/processes/{process_id}
POST /api/bot/processes/{process_id}/pause
POST /api/bot/processes/{process_id}/resume
POST /api/bot/processes/{process_id}/cancel
```

Requirements:

- Stable process IDs; names alone are insufficient.
- Current status and version.
- Allowed transitions.
- Impact preview.
- Required approvers.
- Dependency and customer-impact summary.
- Reversible flag and rollback instructions.
- No generic shell, SQL, service-control, or arbitrary-command endpoint.

## 5. Configuration proposal APIs

The initial design must create proposals, not directly update material settings.

```http
GET  /api/bot/settings/{setting_name}
POST /api/bot/settings/proposals
GET  /api/bot/settings/proposals/{proposal_id}
POST /api/bot/settings/proposals/{proposal_id}/approve
POST /api/bot/settings/proposals/{proposal_id}/apply
POST /api/bot/settings/proposals/{proposal_id}/rollback
```

A proposal must capture:

- Current value and version.
- Proposed value.
- Valid range and unit.
- Reason and supporting evidence.
- Impact assessment.
- Required approval roles.
- Effective time.
- Expiry.
- Rollback value and procedure.

Critical settings, wallet controls, balances, private keys, signing, and direct fund movement remain prohibited.

## 6. Report and calculation APIs

```http
POST /api/bot/reports/calculate
GET  /api/bot/reports/{report_id}
```

Calculations must be deterministic and return:

- Formula/version.
- Input snapshot IDs.
- Observation period.
- Currency and precision.
- Missing/stale input warnings.
- Result and comparison baseline.
- Report ID and content hash.

The LLM explains the result; it must not independently calculate authoritative financial totals.

## 7. Identity and authorization

Production must replace pilot role headers with signed identity claims or service-to-service delegated identity.

Required claims:

- Subject/user ID.
- Tenant.
- Roles and scopes.
- MFA/authentication strength.
- Session/authorization ID.
- Delegation chain.
- Expiry.

The exchange remains authoritative for whether an actor may approve or execute a command.

## 8. Execution safety

All controlled write APIs must support:

- TLS and signed requests.
- Nonce/replay protection.
- Idempotency keys.
- Optimistic concurrency via version or ETag.
- Time-limited authorization.
- Allowlisted operations only.
- Rate limits.
- Dry-run or impact preview where feasible.
- Independent status verification.
- Structured errors.
- Immutable exchange-side audit event.
- Kill switch and per-tool disable flag.

## 9. Prohibited API design

The exchange team must not expose:

- Arbitrary SQL.
- Shell or remote command execution.
- Generic HTTP proxying.
- Raw wallet signing.
- Private key, seed, HSM, or MPC material.
- Direct balance mutation.
- Unrestricted configuration mutation.
- An endpoint that accepts free-form natural language and executes it directly.

Natural language is converted by bitAgent into a typed, validated, allowlisted tool call.

## 10. Handover deliverables

- Updated OpenAPI specification.
- Tool capability catalogue.
- Staging URLs and read-only credentials.
- Signed identity/role test accounts.
- Sample healthy, denied, stale, conflict, and partial responses.
- Idempotency and replay tests.
- Approval-role matrix.
- Setting catalogue with ranges and criticality.
- Process catalogue with allowed transitions.
- Report formula catalogue.
- Audit and verification contract.
- Rollback and kill-switch procedures.
