# Exchange-Side Requirements for XIMA

Audience: exchange engineering, platform, security, data, ledger, wallet,
matching-engine, AML/compliance, support, and SRE owners.

This is the concrete upstream contract required for bitAgent/XIMA to move from
demonstration data to a production-limited exchange intelligence service. The
initial integration is read-only. Controlled actions are a separate, later
scope and must use different credentials, routes, approvals, and network paths.

## 1. Delivery priorities

### P0 — required before a read-only pilot

1. Production-grade bot authentication and authorization.
2. Global exchange/dependency health.
3. Transaction, queue, worker, and network-status evidence.
4. Market list, ticker, order-book depth, trade, and candle evidence.
5. Aggregate ledger liabilities, exchange-controlled wallets, obligations, and
   reconciliation evidence.
6. AML case/risk evidence, security events, and support-ticket evidence with
   strict data minimization.
7. Stable schemas, UTC timestamps, cursor pagination, freshness metadata,
   ownership, rate limits, and structured errors.
8. A sanitized replay dataset and non-production test tenant.

### P1 — required for a mature read-only pilot

1. Event streaming or signed webhooks for material state changes.
2. Historical incident/outcome labels for evaluation.
3. Service dependency topology and capacity evidence.
4. Knowledge-document feed with approval and expiry metadata.
5. Per-source availability/SLA telemetry and maintenance status.
6. Production SSO/JWT identity mapping for human access to bitAgent.

### P2 — controlled-action sandbox only

1. A separate non-production action API and service identity.
2. Exact-parameter preview, validation, idempotency, result verification, and
   rollback/cancel operations.
3. No wallet signing, private keys, direct balance mutation, withdrawal
   approval, fund transfer, autonomous trade, or market shutdown.

## 2. Mandatory platform contract

### 2.1 Authentication

Every bot request must use:

- `X-Bot-Key-ID`: public service-account identifier;
- `X-Request-Timestamp`: Unix seconds;
- `X-Request-ID`: unique UUID, rejected on replay;
- `X-Request-Signature`: HMAC-SHA256 over method, normalized path, exact sorted
  query, timestamp, request ID, and request-body SHA-256;
- optional `X-Tenant-ID` where the credential can access more than one tenant.

The shared secret must never be sent, returned, or logged. The server must
enforce a maximum clock skew, one-time request IDs, per-key scopes, IP/network
allowlists, rate limits, immediate revocation, overlapping-key rotation, and an
audit trail. Read and action credentials must never share a key or scope.

### 2.2 Authorization scopes

Minimum read scopes:

| Scope | Permitted data |
|---|---|
| `health:read` | Service and dependency health |
| `operations:read` | Aggregate operational metrics |
| `transactions:read` | Aggregate transaction state and exceptions |
| `queues:read` | Queue and worker health |
| `networks:read` | Blockchain/network availability |
| `markets:read` | Market, order-book, trades, candles, limits |
| `ledger-summary:read` | Aggregate liabilities and obligations |
| `wallet-summary:read` | Exchange-controlled wallet aggregates |
| `reconciliation:read` | Reconciliation runs and exceptions |
| `risk:read` | Aggregate exposure and counterparty evidence |
| `aml-cases:read` | Minimized case and risk evidence |
| `security-events:read` | Minimized security signals |
| `support:read` | Minimized tickets and outcomes |
| `knowledge:read` | Approved operational documents and metadata |

Credentials should normally be tenant-bound. Cross-tenant aggregation must be
an explicit separate scope and must never expose tenant A evidence to tenant B.

### 2.3 Common response envelope

Every successful response should include:

```json
{
  "schema": {"name": "transactions.summary", "version": "1.0.0"},
  "tenant_id": "exchange-a",
  "source_id": "ledger-primary",
  "owner": "ledger-team",
  "observed_at": "2026-08-01T12:00:00Z",
  "generated_at": "2026-08-01T12:00:01Z",
  "freshness_sla_seconds": 60,
  "data_class": "internal",
  "lineage": ["ledger-db:replica", "aggregation:transactions-v1"],
  "quality": {"complete": true, "warnings": []},
  "data": {}
}
```

Rules:

- Decimal values are strings, never binary floats.
- Currency/asset quantities include asset and precision.
- All timestamps are ISO 8601 UTC with `Z` or an explicit `+00:00` offset.
- Durations are integer milliseconds or seconds and named accordingly.
- Counts are non-negative integers.
- Every identifier states whether it is stable, opaque, and tenant-scoped.
- Null has a documented meaning and is distinct from zero and missing.
- Schema changes are additive within a major version; breaking changes use a
  new major schema and overlap during migration.

### 2.4 Pagination and filtering

Potentially large endpoints require:

- `limit` with a documented maximum;
- opaque `cursor` and `next_cursor`;
- stable ordering with an immutable tie-breaker;
- `observed_from` / `observed_to` UTC filters;
- domain filters such as asset, market, network, status, severity, or queue;
- snapshot consistency or a documented high-water mark;
- a maximum historical lookback and retention statement.

Offset pagination is not acceptable for changing incident, transaction, case,
event, or ticket collections.

### 2.5 Errors and resilience

All errors use a stable envelope:

```json
{
  "error": {
    "code": "rate_limited",
    "message": "Request rate exceeded",
    "request_id": "uuid",
    "retryable": true,
    "retry_after_seconds": 10,
    "details": {}
  }
}
```

Required status behavior: `400` malformed input, `401` missing/expired/bad
signature, `403` denied tenant/scope/IP, `404` absent resource, `409` replay or
state conflict, `422` schema/semantic validation, `429` throttling, `5xx`
dependency failure. Retriable reads must be safe, bounded, and compatible with
exponential backoff and circuit breaking.

## 3. Operations and reliability features

### `GET /api/bot/health`

Required fields:

- overall state: healthy, degraded, unavailable, maintenance;
- component name/type/version/environment/region;
- dependency state and last successful check;
- uptime, request rate, error rate, p50/p95/p99 latency;
- saturation: CPU, memory, disk, connection/thread pools where applicable;
- deployment/version and active maintenance window;
- evidence timestamp and freshness SLA.

### `GET /api/bot/services/dependencies`

- directed service/dependency edges;
- criticality and failure impact;
- current state and last transition;
- owning team, runbook ID, dashboard link identifier;
- redundancy/failover mode.

### `GET /api/bot/operations`

Retain existing counts and add:

- success/failure counts and rates by operation type;
- duration percentiles;
- rejected/cancelled/timed-out totals;
- period boundaries and timezone;
- comparison with previous equivalent period;
- explicit partial-data flags.

### `GET /api/bot/transactions/summary`

- deposits and withdrawals by asset/network/status;
- requested, approved, broadcast, confirmed, failed, rejected counts;
- amount totals as decimal strings;
- pending age buckets and oldest age;
- failure/retry rates and reason-code counts;
- confirmation lag and processing duration percentiles.

### `GET /api/bot/withdrawals/pending` and `/deposits/pending`

- opaque transaction reference, asset, network, status;
- created/updated/broadcast/confirmation timestamps as applicable;
- age, retry count, normalized reason code;
- amount bucket or minimized amount according to approved data class;
- queue/job reference, wallet/provider reference, and correlation ID;
- no address, memo, customer PII, or raw payload unless explicitly approved.

### `GET /api/bot/queues/status`

- queue name, purpose, owner, priority;
- backlog, oldest item age, enqueue/dequeue/complete/failure rates;
- retry/dead-letter counts;
- consumer count, partition lag, capacity and saturation;
- thresholds and last threshold breach.

### `GET /api/bot/workers/status`

- worker pool/type, desired/available/busy/unhealthy counts;
- last heartbeat age, throughput, failure/restart counts;
- current deployment version and capacity limit;
- related queues and dependency state.

### `GET /api/bot/networks/status`

- blockchain/network identifier and enabled state;
- deposit/withdrawal availability with reason;
- node/provider sync height, peer state, lag, fee condition;
- confirmation target and observed confirmation time;
- wallet connectivity and maintenance window;
- last successful broadcast/confirmation timestamps.

## 4. Market, liquidity, and risk features

### `GET /api/bot/markets`

- market symbol, base/quote assets, trading status;
- price/quantity precision and minimums;
- configured limits, maintenance state, and venue/source.

### `GET /api/bot/market/{market}/ticker`

- bid, ask, last, mid, spread, 24h open/high/low/close/volume;
- trade count and evidence timestamp.

### `GET /api/bot/market/{market}/order-book`

- requested depth, sequence number/snapshot ID;
- price/quantity levels for bids and asks;
- cumulative depth within configurable basis-point bands;
- timestamp from matching engine, not only API-generation time.

### `GET /api/bot/market/{market}/trades`

- opaque trade ID, timestamp, price, quantity, aggressor side;
- cursor pagination and high-water mark;
- no customer/account identifier in aggregate scope.

### `GET /api/bot/market/{market}/candles`

- interval, open time, open/high/low/close, base/quote volume, trade count;
- complete/in-progress flag and gap indicators.

### `GET /api/bot/risk/exposure`

- exposure by asset, market, account type, venue, and counterparty class;
- gross/net amount and approved valuation currency;
- valuation time/source and unavailable-price flags;
- configured warning/critical limits and utilization;
- concentration percentages and top-N aggregate buckets.

### `GET /api/bot/risk/market-limits`

- limit identifier, market/asset scope, threshold, current utilization;
- owner, rationale, effective time, approval reference, and breach state.

## 5. Treasury, wallet, liability, and reconciliation features

### `GET /api/bot/ledger/liabilities`

- aggregate customer liability by asset and account class;
- available, locked, pending, and total amounts;
- ledger high-water mark, valuation price/source/time;
- negative/invalid balance count without customer identities.

### `GET /api/bot/treasury/assets`

- exchange-controlled asset totals by asset and custody class;
- hot, warm, cold, custodian, pending, and restricted amounts;
- inclusion/exclusion rules and valuation metadata.

### `GET /api/bot/wallets/summary`

- opaque wallet group, asset, network, custody tier;
- available/pending/locked balances;
- low/high operational thresholds and breach state;
- last inbound/outbound/confirmed activity;
- connectivity and signer availability state only—never keys or seed material.

### `GET /api/bot/treasury/obligations`

- opaque obligation ID/category/asset/status;
- amount, due time, age, owner, priority, and source reference;
- unresolved/overdue reason code.

### `GET /api/bot/reconciliation/runs`

- run ID/type/status/start/end/high-water marks;
- ledger, wallet, custodian, and chain source snapshots;
- matched/unmatched counts and absolute difference by asset;
- approved tolerance and breach state;
- incomplete-source and stale-source flags.

### `GET /api/bot/reconciliation/exceptions`

- opaque exception ID, run ID, asset, category, status, age;
- difference amount, tolerance, evidence references;
- assigned owner, last action time, and normalized reason;
- no automatic adjustment or balance mutation route.

Financial acceptance requires independent fixture calculations for totals,
valuation, precision, rounding, high-water marks, and reconciliation differences.

## 6. AML, fraud, and compliance features

### `GET /api/bot/aml/cases`

- opaque case ID, tenant, status, priority, age, SLA due time;
- normalized risk factors and rule/model versions;
- linked alert/transaction/account counts;
- assigned queue/team, not analyst personal data;
- outcome/false-positive label when closed.

### `GET /api/bot/aml/cases/{case_id}/evidence`

- minimized transaction facts, asset/network, timing, amount buckets;
- rule hits, sanctions/provider result references, behavioral indicators;
- linked-account graph using opaque IDs and documented edge reasons;
- evidence source/time/hash and missing/conflicting warnings;
- no final legal judgment generated by bitAgent.

### `GET /api/bot/aml/queue/summary`

- open/in-review/escalated/closed counts;
- priority and age buckets, SLA breaches, inflow/outflow;
- false-positive/outcome rates by approved aggregate segment;
- oldest cases and capacity indicators without unnecessary PII.

## 7. Security intelligence features

### `GET /api/bot/security/events`

Normalized events from authentication, admin, IAM, WAF, hosts, applications,
and infrastructure:

- event ID, category, action, outcome, severity, timestamp;
- opaque actor/subject/session/device identifiers;
- source/destination network classification (not raw IP unless approved);
- privilege level, authentication strength, geo/ASN risk summary;
- correlation ID, rule ID/version, evidence source, and integrity hash.

### `GET /api/bot/security/incidents`

- incident ID/status/severity/owner/timeline;
- correlated event IDs and deterministic reasons;
- affected services/data classes/tenants;
- containment status and escalation route;
- privileged actions require a separate human-owned source of truth.

### `GET /api/bot/security/privileged-activity`

- opaque actor, role, action, target class, outcome, approval/ticket reference;
- authentication method, timestamp, source classification;
- break-glass use, anomalous context, and policy result.

## 8. Support and governed knowledge features

### `GET /api/bot/support/tickets`

- opaque ticket ID, channel, language, intent, status, age, priority;
- sentiment/dissatisfaction signal and escalation state;
- product area, approved account-state facts, prior-contact count;
- assigned team and SLA; redact credentials, secrets, addresses, documents,
  free-form PII, and authentication factors before model use.

### `GET /api/bot/support/outcomes`

- draft accepted/edited/rejected, escalation correctness, resolution category;
- response and resolution durations;
- customer-satisfaction result where consented;
- aggregate feedback suitable for evaluation.

### `GET /api/bot/knowledge/documents`

- stable document ID, title, type, owner, version;
- approval status and approver role;
- effective, reviewed, and expiry timestamps;
- tenant/audience/data-class permissions;
- content hash, canonical source reference, superseded version;
- chunks or content only for approved, unexpired documents.

Draft, unapproved, expired, cross-tenant, or inaccessible documents must never
be returned to bitAgent retrieval credentials.

## 9. Events and replay

Preferred event delivery is Kafka or another durable ordered log. Signed
webhooks are acceptable for low volume. Required properties:

- immutable event ID, tenant ID, event type/version, occurred/produced time;
- source, owner, data class, correlation and causation IDs;
- partition key and monotonic source sequence where possible;
- at-least-once delivery with consumer idempotency;
- documented ordering scope, retention, replay, backfill, and gap detection;
- dead-letter handling and observable consumer lag;
- schema registry compatibility checks;
- signed webhook body, timestamp, replay protection, retry schedule, and
  receiver acknowledgement where webhooks are used.

Minimum material events: service/dependency state, deployment, queue threshold,
worker loss, network maintenance, deposit/withdrawal status, wallet threshold,
reconciliation completion/exception, market status/limit breach, AML case
state, privileged security event, support escalation, and knowledge approval or
expiry.

The exchange must also provide a sanitized replay package containing normal,
warning, critical, stale, missing, conflicting, duplicate, out-of-order, and
partial-failure cases with expected owner outcomes.

## 10. Human identity integration

For production pilot access, the exchange identity provider must issue signed
OIDC/JWT identity containing stable subject, tenant, roles/groups, authentication
time, MFA assurance, issuer, audience, issue/expiry times, and key ID. Required
controls:

- short token lifetime and JWKS rotation;
- MFA for operators, auditors, approvers, and administrators;
- role mapping owned by identity/security teams;
- immediate deprovisioning and periodic access review;
- no trust in caller-supplied role headers in production;
- separation of maker, checker, executor, auditor, and platform administrator.

## 11. Observability and service levels

Each source needs an agreed owner and target for:

- availability and maintenance windows;
- data freshness and maximum tolerated lag;
- p50/p95/p99 response latency;
- request/error/rate-limit budget;
- retention and backfill window;
- schema-change notice period;
- incident escalation and on-call route;
- recovery point and recovery time objectives.

The exchange should expose credential-free or separately scoped operational
metrics for source availability, last successful generation, data lag, schema
version, partial-data state, and maintenance.

## 12. Controlled-action sandbox contract (later phase)

The only acceptable initial actions are predefined low-risk non-production
runbook steps, case routing, task creation, draft creation, or test notification.
Every action API must support:

- `POST /actions/preview`: exact target, parameters, prerequisites, expected
  effect, risk, evidence, limits, expiry, and rollback plan;
- `POST /actions/validate`: current-state and policy validation with no action;
- `POST /actions/execute`: short-lived signed authorization bound to the exact
  preview hash and idempotency key;
- `GET /actions/{id}`: accepted/running/succeeded/failed/partial/rolled-back
  result with verification evidence;
- `POST /actions/{id}/cancel` or `/rollback` where the action is reversible;
- global and per-action kill switches enforced by the executor, not only UI;
- deterministic timeout and partial-failure behavior;
- immutable maker/checker/executor/result audit records.

Production financial actions remain prohibited unless a later ADR and explicit
steering, security, compliance, and domain approval changes the boundary.

## 13. Exchange-side acceptance evidence

The exchange team must provide reproducible evidence for:

1. Missing signature `401`; expired timestamp `401`; query/body tamper `401`;
   replayed request ID `409`; denied scope/tenant/IP `403`; throttling `429`.
2. Secret absent from requests, responses, logs, traces, metrics, and errors.
3. Key rotation and revocation without downtime.
4. Cross-tenant and cross-scope negative tests for every endpoint.
5. Contract tests for every schema and structured error.
6. Cursor stability under concurrent writes and successful historical replay.
7. Fresh, stale, missing, conflicting, duplicate, and partial-source fixtures.
8. Decimal/rounding and reconciliation results independently verified.
9. Source owner, SLA, lineage, retention, and data classification sign-off.
10. Load, soak, failover, backup/restore, and disaster-recovery results from the
    actual pilot environment.
11. Privacy, compliance, security, and domain-owner acceptance.
12. Proof that all read-only credentials cannot trade, transfer, approve a
    withdrawal, change a balance/user/configuration, or access wallet keys.

## 14. Recommended delivery slices for the exchange team

| Slice | Exchange deliverable | Enables XIMA version |
|---|---|---|
| E1 | Auth, common envelope/errors, health, schema registry, test tenant | 2.0.0 |
| E2 | Dependencies, transactions, pending items, queues, workers, networks | 2.1.0 |
| E3 | Markets, order books, trades, candles, exposure, limits | 2.2.0 |
| E4 | Liabilities, treasury assets, wallets, obligations, reconciliation | 2.3.0 |
| E5 | AML cases/evidence/queue and labeled outcomes | 2.4.0 |
| E6 | Security events/incidents/privileged activity | 2.5.0 |
| E7 | Support tickets/outcomes and governed knowledge documents | 2.6.0 |
| E8 | OIDC/MFA, historical outcomes, operational metrics, owner approvals | 2.7.0–2.8.0 |
| E9 | Separate non-production low-risk action service | 2.9.0 |

Each slice should ship its OpenAPI/schema definitions, owner, SLA, sanitized
fixtures, positive/negative contract tests, and a signed acceptance record.
