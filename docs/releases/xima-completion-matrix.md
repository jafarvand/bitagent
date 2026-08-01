# XIMA Completion Matrix

Assessment date: 2026-08-01  
Software release: `2.11.0`  
Authority: `docs/planning/project-plan.md`

This matrix separates repository-complete capabilities from exchange-side and
human production gates. “Software complete” does not mean a production source,
owner exercise, or steering approval exists.

## Workstream evidence

| Approved-plan requirement | Repository evidence | Software status | Remaining external evidence |
|---|---|---|---|
| Secure foundation | RBAC/refusal policy, hash audits, component registry, CI scans, platform baseline | Complete | Production OIDC/MFA, vault, rotation/revocation, environment and access-review proof |
| Data/integration layer | XIMA evidence contracts, lineage, quality, freshness, replay, source health, resilient GET gateway | Complete | Exchange E1–E7 APIs/events, tenant credentials, schemas, SLAs and sanitized datasets |
| Operations intelligence | Service/dependency/error/latency/capacity, queue/worker, incidents, dedupe, runbook | Complete | Live operations sources and owner-labeled incident outcomes |
| Market/risk intelligence | Spread, depth, volatility, abnormal activity, exposure, concentration, limit breaches | Complete | Order books, trades/candles, exposure/limit feeds and independent owner fixtures |
| Executive intelligence | Required-domain coverage, priorities, owners, KPIs, evidence and next actions | Complete | Scheduled live reports and executive-owner acceptance |
| Treasury/reconciliation | Assets/liabilities, coverage, wallets, obligations, reconciliation/tolerance, brief | Complete | Ledger, wallet, custodian/chain sources and independent financial validation |
| AML/fraud | Transparent scoring, linked patterns, evidence packs, notes, feedback, queue brief | Complete | Minimized AML sources, labeled outcomes and compliance acceptance |
| Security | Auth/admin/IAM/WAF/host/app correlation, privilege checks, narrative, escalation, brief | Complete | Security feeds, incident labels and red-team/security-owner acceptance |
| Support | Intent/urgency/dissatisfaction, PII redaction, safe cited drafts, escalation | Complete | Minimized ticket/outcome feeds and support-owner acceptance |
| Governed RAG | Tenant/role, approval, version, owner, effective/expiry, hash and citation controls | Complete | Approved document feed, residency/retention approval and knowledge-owner review |
| Governance/evaluation | Cross-domain policy, adversarial leakage, quality, refusal, latency, cost, drift, fallback | Complete | Formal privacy/compliance/security review and domain acceptance records |
| Shadow pilot/hardening | Precision/recall, FP/FN, noise, SLA, latency and reliability evidence evaluator | Complete | Actual shadow outcomes, target-environment load/soak/failover/restore, training and rehearsal |
| Controlled-action readiness | Preview, exact signed maker-checker auth, expiry, single-use, idempotency, timeout, partial failure, verify, rollback, kill switch | Complete | Separate exchange sandbox executor and formal go/no-go; production financial actions remain prohibited |

## Epic audit

| Epic | Implemented software | Exchange/external dependency that remains |
|---|---|---|
| A — Platform/integration | Auth v0.2 client, evidence/schema contracts, replay, freshness, quality, retry/circuit/telemetry | Source catalog values, credentials, rate/SLA confirmation, live event ingestion |
| B — Operations | Dependency, errors, latency, queues/workers, capacity, incidents, similar refs, runbook, brief inputs | Required upstream operations endpoints and outcome labels |
| C — Market/risk | Spread/depth, volatility, abnormal activity, exposure/concentration, breaches, quality brief | Order-book, trades, candle, exposure and limit endpoints |
| D — Treasury | Assets/liabilities, wallet thresholds, obligations, reconciliation, aging, brief | Ledger/wallet/custodian/chain aggregate endpoints |
| E — AML/fraud | Priority factors, linked patterns, transaction packs, notes, corrections, queue brief | AML platform contract, minimized data approval and owner outcomes |
| F — Security | Cross-source correlation, privilege review, narrative, escalation, brief | SIEM/IAM/WAF/host/app feeds and incident-response integration |
| G — Support/knowledge | Classification, drafts, escalation, governed retrieval, expiry, corrections | Support and approved-document feeds plus owner validation |
| H — Governance/model ops | RBAC, policy, approvals, audit, registry, evaluations, drift, kill switch, rollback | Production identity, operational dashboards and approval evidence |

## Current production decision

The repository is software-complete for the versioned XIMA plan through
`2.11.0`, but it is **not approved for a production-controlled-action launch**.
The next concrete dependency is the exchange-side E1–E8 delivery and evidence
package described in `docs/integration/exchange-side-requirements.md`.

Read-only production pilot eligibility must be decided from actual source,
identity, security, privacy, reliability, training and domain-owner evidence.
Controlled production actions require an additional steering and
security/compliance go/no-go and are never enabled automatically.
