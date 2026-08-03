# Exchange API 0.8 staging integration report

Prepared for: Exchange engineering, platform, matching-engine, treasury, and security teams  
Test date: 2026-08-02 UTC  
bitAgent release: `2.17.0`
Exchange contract: `0.8.0-pilot`  
Environment: isolated synthetic staging

## Executive result

The credential/host mismatch is resolved. bitAgent now uses the staging key ID
`bitagent-staging-01` only with `https://staging-devapi.zekabot.com`. The secret
was loaded locally and was not printed, committed, returned by an API, or placed
in this report.

All 14 OpenAPI routes were called through the production signing implementation.
Authentication and signing succeeded for every request. Eleven routes returned
valid contract envelopes. Three returned structured `502` dependency errors,
matching the staging documentation that no matching-engine replica is present.

| Outcome | Count | Assessment |
|---|---:|---|
| Valid successful envelope | 11 | Pass |
| Structured expected dependency failure | 3 | Environment-limited, contract behavior passes |
| Authentication failure | 0 | Pass |
| Undocumented/unstructured failure | 0 | Pass |
| Sensitive credential exposure | 0 | Pass |

## Environment and authentication

| Item | Tested value | Result |
|---|---|---|
| Base URL | `https://staging-devapi.zekabot.com` | Correct staging host |
| Key ID | `bitagent-staging-01` | Correct staging key |
| Authentication | Four-header HMAC-SHA256 | Accepted |
| Query signing | Sorted encoded query included in canonical string | Accepted on parameterized routes |
| Secret handling | Local environment only | Not exposed |
| Previous failure | Staging key used against production `devapi` | Resolved by correct host/key pairing |

`.env.bitagent-staging-db` was deliberately not used. Database credentials are
not application API credentials and must remain separated from bitAgent.

## Endpoint results

| # | Endpoint | Schema/result | Quality | Time | Status | Exchange-team interpretation |
|---:|---|---|---|---:|---|---|
| 1 | `GET /api/bot/health` | `health` | Complete | 336 ms | Pass | API, auth, database health contract available |
| 2 | `GET /api/bot/transactions/summary` | `transactions.summary` | Complete | 209 ms | Pass | Aggregate open-count evidence available |
| 3 | `GET /api/bot/withdrawals/pending?limit=2` | `withdrawals.pending` | Complete | 177 ms | Pass | Cursor-paginated withdrawal evidence available |
| 4 | `GET /api/bot/deposits/pending?limit=2` | `deposits.pending` | Complete | 197 ms | Pass | Cursor-paginated deposit evidence available |
| 5 | `GET /api/bot/operations?...` | `operations` | Complete | 214 ms | Pass | Signed date query and aggregate evidence valid |
| 6 | `GET /api/bot/market/BTC_USDT/summary` | `market_service_failed` | N/A | 1,407 ms | Expected 502 | Matching engine intentionally absent in staging |
| 7 | `GET /api/bot/ledger/liabilities` | `ledger.liabilities` | Complete | 147 ms | Pass | Synthetic ledger snapshot aggregation valid |
| 8 | `GET /api/bot/treasury/assets` | `treasury.assets` | Partial | 190 ms | Pass with warnings | Degraded-source semantics work; investigate warnings before production acceptance |
| 9 | `GET /api/bot/user/1/summary` | `userSummary` | Complete | 171 ms | Pass | Minimized user summary available |
| 10 | `GET /api/bot/user/1/balances` | `balance_service_failed` | N/A | 1,265 ms | Expected 502 | Matching engine intentionally absent in staging |
| 11 | `GET /api/bot/user/1/trades?...` | `trade_history_failed` | N/A | 1,279 ms | Expected 502 | Matching engine intentionally absent in staging |
| 12 | `GET /api/bot/user/1/deposits?...` | `deposits` | Complete | 179 ms | Pass | Date/limit query and masked records valid |
| 13 | `GET /api/bot/user/1/withdrawals?...` | `withdrawals` | Complete | 167 ms | Pass | Date/limit query and masked records valid |
| 14 | `GET /api/bot/user/1/pnl?...` | `pnl` | Complete envelope | 166 ms | Pass with product limitation | PnL remains execution-only and must report incomplete calculation |

Times are single observed staging round trips and are not latency SLO evidence.

## bitAgent integration results

| Integration | Result | Interpretation |
|---|---|---|
| Transaction intelligence | `200`, `ready` | Health, summary, withdrawals, and deposits combine successfully |
| Treasury intelligence | `200`, `partial`, severity `unknown` | Correct fail-closed behavior while treasury quality is incomplete |
| User investigation before follow-up fix | `502 balance_service_failed` | bitAgent discarded four valid sources when two matching-engine sources failed |
| User investigation after follow-up fix | `200`, `partial`, confidence `limited` | Live verification returns available summary/deposit/withdrawal/PnL evidence with explicit `balances` and `trades` source errors |

## Problems and required actions

| ID | Severity | Problem | Evidence | Owner | Required action | Acceptance evidence |
|---|---|---|---|---|---|---|
| EX-01 | High for production testing | Staging has no matching-engine replica | Three structured 502 results | Exchange platform / matching-engine | Provide an isolated synthetic matching-engine dependency or a deterministic stub for market, balances, and trades | All three routes return valid synthetic envelopes, plus tested outage-mode 502 fixtures |
| EX-02 | High for production readiness | Treasury response is incomplete | `quality.complete=false` on `treasury.assets` | Treasury / exchange backend | Resolve or formally accept wallet refresh and Jibit staging warnings; provide freshness thresholds | Complete synthetic happy-path fixture and separate partial-source fixture both pass |
| EX-03 | High | Production key/host remains untested in this run | Only staging credentials were supplied | Exchange security / platform | Supply or register `bitagent-pilot-01` for `https://devapi.zekabot.com` with least-privilege scopes and IP allowlist | All production-safe aggregate routes authenticate; no user-level test without approval |
| EX-04 | Medium | Market OHLC may be zero/incomplete in production evidence | Earlier production snapshot had zero open/high/low/volume | Matching-engine / market data | Return genuine observed OHLCV or mark quality incomplete with warning codes | Non-zero coherent OHLCV fixture; invalid fixture produces `quality.complete=false` |
| EX-05 | Medium | Historic open transaction rows can be years old | Contract and staging fixtures reproduce stale-row condition | Operations / data owner | Define active-backlog ceiling or normalized stale/abandoned status | Owner-approved rule and labeled fixtures prevent permanent false alerts |
| EX-06 | Medium | User PnL is incomplete | `calculation_complete=false`, weighted-average ledger absent | Ledger / finance product | Connect approved cost-basis ledger or retain explicit incomplete status | Independent finance fixture validates realized/unrealized PnL and fees |
| EX-07 | Medium | User activity routes are limit-only | OpenAPI v0.8 contract | Exchange backend | Add cursor/high-water-mark pagination for potentially large histories | Multi-page no-gap/no-duplicate tests |
| EX-08 | Low/technical debt | Legacy timestamps are MySQL UTC strings, not RFC 3339 | OpenAPI timestamp note | Exchange backend | Normalize in a versioned contract without breaking existing consumers | Schema tests enforce offset-aware UTC timestamps |

## Security and data-handling observations

- No trade, transfer, withdrawal approval, balance mutation, user mutation, or
  configuration-write route was called or added.
- The browser diagnostic console receives schema, quality, timing, keys, and
  counts only; raw transaction, balance, treasury, address, and hash values are
  suppressed.
- User investigation output minimizes raw rows and explicitly reports source
  failures and incomplete PnL.
- Staging and production key IDs, secrets, URLs, scopes, and allowlists must be
  managed as separate profiles. A staging key must never be used with the
  production host.

## Exchange-team acceptance checklist

- [ ] Confirm `bitagent-staging-01` scopes and IP allowlist are intentional.
- [ ] Add synthetic matching-engine success coverage for the three dependent routes.
- [ ] Preserve the current structured 502 outage fixtures after adding success coverage.
- [ ] Provide a complete treasury happy-path fixture alongside degraded Jibit/wallet fixtures.
- [ ] Decide and document treatment of multi-year stale pending rows.
- [ ] Provide production key registration and a safe aggregate-only validation window.
- [ ] Confirm owner-approved freshness SLAs and quality-warning codes per endpoint.
- [ ] Add cursor pagination to legacy user histories or document a bounded operational limit.
- [ ] Return updated OpenAPI/Postman artifacts after any contract change.

## Reproduction

Use the bitAgent page `/exchange-api-test`, select the staging profile through
the configured deployment environment, and run all endpoints. The API catalog
is automatically checked against every path in `docs/openapi.yaml`; CI fails if
the copied contract and connector catalog diverge.
