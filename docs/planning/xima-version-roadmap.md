# XIMA Remaining Delivery Roadmap

Baseline: `1.10.0`  
Authority: `docs/planning/project-plan.md`  
Mode: read-only evidence and advisory outputs first; controlled actions remain
local/sandbox-only until separately approved.

This roadmap converts the remaining implementable work in the approved
16-week Exchange Intelligence and Management Agent plan into testable releases.
It does not treat external credentials, owner sign-off, production identity,
training, or steering approval as software features.

| Version | Focus | Exit result | Status |
|---|---|---|---|
| `2.0.0` | Evidence platform | Versioned multi-domain evidence contracts, lineage, freshness, quality, tenant isolation, source health, and replay | Complete |
| `2.1.0` | Operations intelligence | Dependency, error, latency, queue, worker, capacity, deduplication, incident, and runbook analysis | Complete |
| `2.2.0` | Market and risk | Spread, depth, volatility, exposure, concentration, abnormal activity, limit explanations, and market-quality brief | Complete |
| `2.3.0` | Treasury and reconciliation | Assets, liabilities, wallet thresholds, obligations, reconciliation exceptions, aging, and treasury brief | Complete |
| `2.4.0` | AML and fraud | Transparent case priority, linked-account and behavior evidence, transaction risk packs, notes, feedback, and queue brief | Complete |
| `2.5.0` | Security intelligence | Authentication, privileged activity, WAF, host, application, and IAM correlation with escalation and daily brief | Complete |
| `2.6.0` | Support and governed knowledge | Ticket classification, safe drafts, escalation, cited retrieval, ownership, approval, version, and expiry workflow | Complete |
| `2.7.0` | Governance and evaluation | Domain/data/environment/risk policy, registry, adversarial checks, quality/latency/cost evaluation, fallback, and escalation | Complete |
| `2.8.0` | Shadow pilot and reliability | Outcome comparison, alert precision/recall, duplicate/noise reporting, load/soak/failover/restore evidence, and readiness gates | Complete |
| `2.9.0` | General action sandbox | Risk-classified previews, maker-checker separation, exact signed authorization, expiry, idempotency, timeout, result verification, rollback, and kill switch | Complete |
| `2.10.0` | Executive intelligence | Cross-domain coverage, KPIs, prioritized risk/incident summary, evidence, owners, and next actions | Complete |
| `2.11.0` | Secure delivery and gateway | Bounded retry/backoff, circuit breaker, source telemetry, CI security scans, environment, logging, retention, and release baseline | Complete |
| `2.12.0` | Audited output channel | Tenant-scoped append-only agent/report feed, payload receipts, and independent integrity verification | Complete |

## Definition of software completion

- Every output identifies tenant, evidence time, evidence references, freshness,
  confidence, severity or priority, limitations, owner, and next action.
- Missing, stale, conflicting, cross-tenant, or malformed evidence fails closed.
- Deterministic financial and policy calculations have direct tests.
- Every local mutation is role-gated and append-only audited.
- No exchange trade, transfer, withdrawal, balance, user, wallet-signing, or
  configuration write is introduced.
- Every version has API tests, changelog evidence, and a reproducible container
  test run.

## External production gates (not satisfiable by repository code alone)

- Read-only production credentials, source endpoints, network allowlists, vault,
  rotation, and revocation evidence.
- Production SSO/JWT, MFA, identity-owner approval, and access review.
- Sanitized owner incidents and live shadow outcomes for domain acceptance.
- Privacy, compliance, security, operations, support, treasury, AML, and risk
  owner acceptance records.
- Load/soak/failover execution in the target infrastructure, operator training,
  on-call rehearsal, and disaster-recovery exercise records.
- Steering-committee go/no-go approval for any production controlled action.

These gates must remain visible as pending until signed evidence is supplied.
