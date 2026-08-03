# Chat-First Command Orchestrator

**Status:** Required product capability  
**Target release:** 2.17.0 foundation, expanded in 2.18.0–2.20.0  
**Primary rule:** Chat is the operating interface. Forms and menus are optional visibility tools, not required workflow steps.

## Product requirement

A manager must be able to ask bitAgent to search, view, investigate, calculate, generate reports, approve, reject, pause, resume, cancel, or propose setting changes using natural-language chat commands.

The agent must:

1. Detect the requested intent and target.
2. Retrieve only authorized evidence.
3. Ask conversationally for only the missing required fields.
4. Preserve command state across turns.
5. Resolve ambiguous targets before execution.
6. Check role, policy, evidence freshness, risk, and approval requirements.
7. Present an exact preview for material changes.
8. Execute only registered and allowlisted tools.
9. Verify the result from the authoritative system.
10. Report what changed, what did not change, limitations, timestamps, IDs, and rollback availability.
11. Record the request, evidence, approvals, tool call, response, and verification in an append-only audit trail.

## Interaction contract

```text
Chat request
  -> intent/entity extraction
  -> conversational slot collection
  -> authorization and policy
  -> risk classification
  -> confirmation/approval
  -> tool execution
  -> authoritative verification
  -> chat result and audit receipt
```

The LLM may interpret language and prepare structured arguments. Deterministic services remain authoritative for permissions, calculations, limits, approvals, and execution.

## Command classes

- Read-only: search, view, list, investigate, compare, calculate, generate report.
- Low-risk controlled: create task, route case, schedule report, pause campaign, send approved notification.
- Material controlled: approve/reject workflow, pause operational process, propose configuration change.
- Prohibited without separate governance: move funds, sign wallets, alter balances, autonomous trading, disable critical controls.

## Release plan

### 2.17.0 — Orchestrator foundation

- Deterministic intent classification.
- Tool registry and required-field schema.
- Multi-turn command state.
- Missing-information prompts.
- Role and risk classification.
- Read-only execution plans.
- Write-command previews that execute nothing.

### 2.18.0 — Conversational read-only execution

- Connect search, evidence retrieval, investigations, calculations, and report tools.
- Verify evidence freshness and data quality.
- Return report IDs and audit receipts in chat.

### 2.19.0 — Conversational approvals

- Approval inbox lookup by chat.
- Approve, reject, cancel, and status commands.
- Maker-checker separation, expiry, idempotency, and signed authorization.
- Explicit confirmation for material actions.

### 2.20.0 — Allowlisted controlled execution

- Execute approved low-risk tools.
- Verify authoritative post-state.
- Rollback where supported.
- Kill switch and per-tool feature flags.
- No direct fund movement or wallet signing.

## Acceptance criteria

- No workflow requires a form when all required information can be collected in chat.
- The agent never invents a missing parameter.
- Ambiguous targets are not executed.
- A write command cannot bypass policy or approval.
- Every execution result is verified independently of the LLM.
- Stale, partial, conflicting, or unavailable evidence is disclosed and fails closed where material.
- Every command has a stable command ID, correlation ID, actor, role, timestamp, and audit receipt.
