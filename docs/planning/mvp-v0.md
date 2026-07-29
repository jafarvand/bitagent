# bitAgent Version 0 — MVP Plan and Task Board

Version: `0.0.1`  
Release name: **Visibility Shell**  
Mode: read-only; mock by default  
Target: connect the existing exchange API safely and show exactly what is
available, partial and missing.

## Outcome

An operator can open one page and see:

- whether bitAgent is in mock or live mode;
- exchange operations counts for a selected period;
- pending withdrawals and the present evidence boundary;
- a selected market snapshot;
- the implemented API coverage and required next endpoints.

## Version 0 feature list

| Feature | State | Evidence/API |
|---|---|---|
| Runtime status and version | Done | `/api/v0/status`, `/health` |
| Mock/live operating mode | Done | Environment-controlled |
| Operations totals | Done | `/api/bot/operations` |
| Market snapshot | Done | `/api/bot/market/{market}/summary` |
| Pending-withdrawal signal | Done, limited | Count only |
| User investigation proxy | Done, API-only | Six user endpoints |
| Feature coverage matrix | Done | `/api/v0/features` |
| Minimum responsive dashboard | Done | `/` |
| Docker packaging | Done | `Dockerfile`, Compose |
| Connector/unit tests | Done | `tests/` |
| Complete PnL | Partial | Cost-basis ledger missing |
| Slowdown root-cause analysis | Partial | Queue/worker/age data missing |
| Treasury and liabilities | Missing | New endpoints required |
| Reconciliation | Missing | New endpoint required |
| Liquidity/depth risk | Missing | Order-book endpoint required |

## Definition of done for 0.0.1

- [x] App starts without a secret in safe mock mode.
- [x] Live mode refuses to run an upstream call without a token.
- [x] Exchange client signs requests according to the current pilot contract.
- [x] UI renders operations, market, signal and feature coverage.
- [x] No write route or upstream write request exists.
- [x] Secrets and local environment files are ignored by Git.
- [x] Version and limitations are documented.
- [ ] Run automated tests in a clean environment.
- [ ] Confirm Docker build on the deployment host.
- [ ] Run a live staging smoke test with a read-only token.
- [ ] Confirm IP allowlist and token revocation procedure.
- [ ] Product owner accepts the minimum dashboard.

## Prioritized backlog

### P0 — make live pilot safe

- [ ] Replace bearer-secret header with `X-Bot-Key-ID`.
- [ ] Sign normalized path, sorted query, timestamp, request ID and body hash.
- [ ] Reject replayed request IDs server-side.
- [ ] Add per-key rate limits, scopes, rotation and immediate revocation.
- [ ] Add IP allowlist before production access.
- [ ] Complete OpenAPI response schemas and common error schemas.
- [ ] Add cursor pagination to potentially large endpoints.
- [ ] Standardize timestamps to ISO 8601 UTC.
- [ ] Add `/api/bot/health`.
- [ ] Add structured audit events without secrets or personal data.

### P1 — withdrawal/deposit slowdown pilot

- [ ] Add `/api/bot/transactions/summary`.
- [ ] Add `/api/bot/withdrawals/pending`.
- [ ] Add `/api/bot/deposits/pending`.
- [ ] Add `/api/bot/networks/status`.
- [ ] Add `/api/bot/queues/status`.
- [ ] Add `/api/bot/workers/status`.
- [ ] Define thresholds for pending age, backlog and failure rate.
- [ ] Build deterministic incident detection.
- [ ] Show evidence timeline and affected asset/network.
- [ ] Add acknowledge/resolve workflow and audit history.

### P2 — treasury and risk

- [ ] Add aggregate liabilities by asset.
- [ ] Add exchange-controlled treasury balances.
- [ ] Add reconciliation differences and tolerance configuration.
- [ ] Add markets list and order-book summary.
- [ ] Calculate spread, depth, divergence, exposure and concentration.
- [ ] Add daily executive brief.

### P3 — controlled AI assistance

- [ ] Add runbook retrieval with source citations.
- [ ] Add natural-language questions over normalized evidence.
- [ ] Require timestamps, confidence and stale-data warnings in every answer.
- [ ] Add evaluation fixtures and historical incident replay.
- [ ] Add feedback/correction workflow and model-cost visibility.

## Next release

`0.1.0` begins only after P0 security and API-contract tasks are complete. Its
exit result is a staging-ready connector with health and transaction-summary
data, complete schemas and replay resistance.
