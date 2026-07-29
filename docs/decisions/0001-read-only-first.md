# ADR-0001: Read-only first

Status: Accepted  
Date: 2026-07-29

## Decision

bitAgent version 0 and the first pilot expose only read operations. The system
must not trade, move funds, approve withdrawals, change balances, suspend users,
or modify exchange configuration.

## Reasons

- Validate evidence quality and operational usefulness before action authority.
- Limit financial, security and compliance impact during early integration.
- Make historical replay and shadow-mode testing possible.
- Keep every recommendation subject to human review.

## Consequences

- The current connector implements only `GET`.
- Write capabilities are not hidden feature flags; they are absent.
- Early value comes from monitoring, investigation and reporting.
- Any future write workflow requires a separate ADR, explicit scopes, approval
  policy, idempotency, audit, rollback and security review.
