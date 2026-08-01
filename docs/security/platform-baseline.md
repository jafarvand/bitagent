# XIMA Platform Security and Operations Baseline

This baseline defines repository-enforceable controls. Production evidence and
owner approvals remain external gates.

## Environments

| Environment | Data | Identity | Exchange access | Actions |
|---|---|---|---|---|
| Development | Synthetic only | Local developer | Mock by default | Local sandbox only |
| Test | Sanitized fixtures | CI workload | Mock/contract stub | Local sandbox only |
| Staging | Approved minimized data | Staging SSO/service account | Read-only staging scopes | Low-risk non-production sandbox |
| Pilot | Approved production aggregates | Production SSO/MFA | Tenant-bound read-only scopes | Disabled without separate go/no-go |

Environment databases, identities, network routes, credentials, and encryption
keys must be separate. Production data must not be copied to development.

## Secrets

- Secrets are supplied through the deployment secret manager, never Git, image
  layers, URLs, prompts, logs, traces, errors, or metrics.
- Bot keys are scope- and tenant-bound, IP-allowlisted, immediately revocable,
  and rotated with an overlapping-key procedure.
- Read and action identities, secrets, and network routes are separate.
- CI runs repository secret scanning. Findings block release.

## Logging and redaction

- Log request IDs, opaque actor/tenant/source IDs, route, status, duration,
  schema version, and safe error code.
- Never log authorization headers, signatures, tokens, secrets, passwords,
  private/seed keys, raw support text, wallet addresses, identity documents, or
  unnecessary customer identifiers.
- Use field allowlists for restricted domains. Redaction occurs before log,
  prompt, trace, or metric creation.
- Security access, local mutations, approvals, executions, and outcomes use
  append-only hash-chained audit records.

## Retention and deletion

| Data class | Default maximum | Required handling |
|---|---:|---|
| Public | 365 days | Integrity and ownership metadata |
| Internal | 180 days | Tenant isolation and role control |
| Confidential | 90 days | Encryption, restricted export, owner review |
| Restricted | 30 days | Explicit purpose, auditor/admin access, no model retention |

Legal/regulatory owners may specify a different approved period. Expiry must
remove data from active stores and scheduled backups according to the approved
deletion process. Audit receipts may retain hashes and non-sensitive metadata
where legally approved. Right-to-erasure requests must remove linkable content
without falsifying immutable audit history.

## Resilience and safe failure

- Exchange reads use timeouts, bounded retries only for transport, `429`, and
  `5xx` failures, exponential backoff, and a circuit breaker.
- `4xx` authentication, authorization and validation failures are not retried.
- Stale, missing, conflicting, cross-tenant, or invalid evidence blocks material
  conclusions and actions.
- Action sandbox authorizations are short-lived, single-use, exact-parameter,
  idempotent, kill-switch controlled, verified, and audited.
- Backup/restore, failover, load and soak evidence is required from the target
  environment before pilot acceptance.

## CI/CD and release checklist

CI must pass compilation, unit/API tests, dependency audit, secret scan,
container build and high/critical container vulnerability scan. A release also
requires:

1. Version, changelog, API and runbook documentation updated.
2. Contract and negative authorization tests passed.
3. Audit, redaction, stale/conflict and rollback behavior tested.
4. Schema/config/model/prompt/tool/rule versions recorded.
5. Target-environment backup/restore and rollback procedure verified.
6. Domain acceptance and required security/privacy/compliance evidence attached.
7. Production action state remains disabled unless separately approved.
