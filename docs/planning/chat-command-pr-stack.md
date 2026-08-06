# Chat-First Command Orchestrator — Stacked PR Implementation Map

This document records the implementation branches created from the latest `main` line.

## Open draft PR

1. `integration/chat-orchestrator-sync` → `main`
   - Management question readiness catalog
   - Chat command intent, typed tools, slot collection, role/risk/approval planning
   - Safety tests

## Stacked branches awaiting review after PR #1

2. `feature/chat-session-runtime`
   - Tenant/user-scoped persistent sessions
   - Optimistic state-hash locking
   - Expiry and cancellation
   - Append-only session events
   - FastAPI command router

3. `feature/chat-readonly-tools`
   - Read-only tool handler registry
   - Role and required-field checks
   - Evidence, timestamp and source verification
   - Fail-honest execution receipts

4. `feature/chat-approval-workflows`
   - Approval request store
   - Single-approval and maker-checker workflows
   - Version checks, expiry, idempotency and cancellation

5. `feature/command-verification-audit`
   - Persistent command receipts
   - Tenant-scoped retrieval
   - Hash-chain integrity verification
   - Pending-verification status boundary

6. `feature/exchange-command-contracts`
   - Typed capability contracts
   - Identity claims
   - Contract and envelope hashing
   - Prohibited generic execution-tool rejection

7. `feature/chat-controlled-actions`
   - Injected controlled-action transport
   - MFA, role, tenant, approval and exact-plan checks
   - Source verification and reversible rollback
   - No concrete exchange transport or credentials

8. `test/chat-command-evaluation`
   - Golden command evaluation framework
   - Intent, tool, slot, authorization, prompt injection and unsafe-action gates
   - Minimum 95% overall and 100% safety-category gates

9. `release/chat-command-shadow-pilot`
   - Shadow outcome comparison
   - Intent/tool/status/verification/latency/override metrics
   - Pilot execution policy
   - External owner and operational go-live gates

## Safety boundary

No branch introduces a generic shell, SQL, arbitrary HTTP proxy, wallet-signing, private-key, seed, balance-mutation, or unrestricted configuration endpoint. Controlled exchange writes remain impossible until the exchange team supplies approved capability contracts, identity, approval, idempotency, verification and rollback transports.

## Verification still required

- Run the full test suite in a real checkout or GitHub Actions.
- Wire `app.command_api.router` into `app.main` after PR #1 review.
- Resolve any lint/type issues found by CI.
- Open later PRs one at a time after their base PR merges.
- Complete staging integration with exchange-owned APIs and credentials.
