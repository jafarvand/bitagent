# bitAgent read-only pilot — exchange-backend

Companion to `openapi.yaml` and `bitAgent.postman_collection.json` in this folder.

## Backend technology

- **exchange-backend**: PHP 7.2, Phalcon 3.3.1 (MVC), running under Apache 2.4/mod_php in Docker. Routes defined in `config/exchange-backend/html/config/routes.php`; the bot-facing controller is `data/exchange-backend/apps/Rest/Controller/BotController.php`.
- **Matching engine**: C (`exchange-core`), reached from PHP only via an internal JSON-RPC client (`Core\Plugin\JsonRPC`) — no direct DB access to it from this controller.
- **MySQL**: `exchange-backend-mysql` backs `User`, `Deposit`, `Withdraw`, `UserOrder`, `IncomeDetail` models used here.
- **Deployment**: single-host Docker Compose (no k8s). `exchange-backend`'s `apps/` and `config/` are bind-mounted from the host, so PHP edits take effect immediately — no image rebuild needed; only a container recreate (`docker compose up -d exchange-backend`) is needed when env vars change.

## Authentication method

Custom HMAC-SHA256 service-to-service signing — **not** JWT, not a plain API key. Implemented in `Core\Security\BotServiceAuth` (+ `Core\Security\BotNonceStore` for replay protection), enforced in `BotController::beforeExecuteRoute`.

**v0.2 — the secret is never transmitted.** The v0.1 pilot design sent the shared secret itself as the bearer token on every request (`X-Exchange-Bot-Authorization: Bearer <secret>`), which meant capturing one request disclosed the secret and let an attacker sign new ones — the HMAC added no real protection over a plain static token. v0.2 fixes this: the caller identifies *which* key it's using via `X-Bot-Key-ID`, the server looks up the matching secret itself, and the caller only ever proves possession of the secret through the signature.

**Signing recipe:**
1. Canonical string (fields joined with `\n`):
   ```
   METHOD
   PATH
   SORTED_QUERY_STRING
   TIMESTAMP
   REQUEST_ID
   BODY_SHA256_HEX
   ```
   - `METHOD`: uppercase, e.g. `GET`.
   - `PATH`: URL path only, e.g. `/api/bot/operations` — no host, no query string.
   - `SORTED_QUERY_STRING`: query params sorted by key (byte order), each pair `rawurlencode(key)=rawurlencode(value)`, joined by `&`; empty string if none. **This must cover every query param** — v0.1's canonical string omitted the query entirely, so an intermediary could rewrite `date_from`/`date_to` on a signed request without invalidating the signature. Verified fixed: a tampered `date_from` on an otherwise-validly-signed request now gets rejected with 401 (tested 2026-07-29).
   - `TIMESTAMP` / `REQUEST_ID`: the literal values also sent in the headers below.
   - `BODY_SHA256_HEX`: sha256 of the raw body, lowercase hex. Every current endpoint is GET with no body, so this is always the empty-string hash: `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`.
2. `signature = lowercase_hex(HMAC-SHA256(canonical, shared_secret))`.
3. Send four headers on every request:
   - `X-Bot-Key-ID: <key id>` — e.g. `bitagent-pilot-01`. Identifies which secret to use; the secret itself is never sent.
   - `X-Request-Timestamp: <unix seconds>` — must be within 60s of server time.
   - `X-Request-ID: <uuid>` — v1-5 UUID, **single-use**: replaying an already-seen ID now gets rejected with 409 (`BotNonceStore`, file-based claim under `temp/bot_nonces/`, retained 5 minutes — longer than the 60s clock-skew window so a nonce can't "expire back into" validity).
   - `X-Request-Signature: <hex hmac>`.
4. Secrets live in `.env.bitagent` at the repo root as `EXCHANGE_BOT_SERVICE_KEYS=key_id:secret,key_id2:secret2` (comma-separated `key_id:secret` pairs — add a new pair to rotate without downtime, remove one to revoke immediately), loaded into the `exchange-backend` container via `env_file` in `docker-compose.yml`. **Not committed to the config file itself, not printed in this doc.** A container recreate (`docker compose up -d exchange-backend`) is required after editing `.env.bitagent` for the new keys to take effect.
5. Optional IP allowlist via `EXCHANGE_BOT_ALLOWED_IPS` (comma-separated) — **configured as of 2026-07-30** with the bitAgent host's egress IP(s) plus `127.0.0.1` for local testing. Update this file directly (`.env.bitagent`) and recreate `exchange-backend` when the bitAgent's egress IP changes.
6. Per-key rate limiting: `EXCHANGE_BOT_RATE_LIMIT_PER_MINUTE` (default 120), file-counter based under `temp/bot_ratelimit/`. Exceeding it returns 429.
7. Every auth outcome (success, bad signature, IP denied, rate limited, replay, config missing) is logged via `error_log` — visible in `docker compose logs exchange-backend`, tagged `[bot-auth]` with `event`, `key_id`, `request_id`, `ip`, `path`.
8. All failures return a structured JSON error (`{"error":{"code","message","request_id"}}`) with the appropriate status: 503 config missing, 403 IP denied, 429 rate limited, 401 bad/missing signature, 409 replay.

There is no write, trade, transfer, or withdrawal action reachable through this controller — an earlier `cancelOrderAction` was removed before routing anything live.

**Still open on auth:** key revocation/rotation is supported by the `EXCHANGE_BOT_SERVICE_KEYS` format described above, but there's no tooling around it yet (it's a manual `.env.bitagent` edit + container recreate) — fine for a single pilot key, would want a real process before onboarding multiple consumers.

## Available read-only endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/bot/health` | Backend + dependency health (database, matching engine) with per-component latency |
| GET | `/api/bot/transactions/summary` | Exchange-wide open deposit/withdrawal counts by status, right now (not date-ranged) |
| GET | `/api/bot/withdrawals/pending` | All in-flight withdrawals, exchange-wide, oldest first, cursor-paginated |
| GET | `/api/bot/operations` | Aggregated deposit/withdrawal/order counts + fee revenue for a date range |
| GET | `/api/bot/market/{marketIdentifier}/summary` | Single market ticker/status (e.g. `BTC_USDT`) |
| GET | `/api/bot/user/{userId}/summary` | Account status, KYC level, order counts |
| GET | `/api/bot/user/{userId}/balances` | Per-asset available/blocked/total + IRT valuation |
| GET | `/api/bot/user/{userId}/trades` | Executed trades in a date range |
| GET | `/api/bot/user/{userId}/deposits` | Deposit records in a date range (tx hash/destination masked) |
| GET | `/api/bot/user/{userId}/withdrawals` | Withdrawal records in a date range (tx hash/destination masked) |
| GET | `/api/bot/user/{userId}/pnl` | Execution PnL in a date range (partial — cost-basis ledger not connected yet) |

**Known gap:** none of these give aggregated **treasury** (exchange hot-wallet balances) or **liabilities** (aggregate customer balance per asset across all users) data — see "Not yet built" below.

**⚠️ Data-quality trap — read before wiring up alerts:** `transactions/summary` and `withdrawals/pending` both surface an `oldest_open_*` age. Live on 2026-07-30, the oldest "open" deposit was from **2022-02-01** and the oldest "open" withdrawal from **2022-06-26** — both over 4 years old. These are almost certainly stale/abandoned rows never properly closed out in the database, not an active incident. **Do not alert directly on the raw age value** — it will fire immediately and permanently. Either cap what counts as "genuinely pending" at some reasonable ceiling (a business decision, not made here), or alert on the *rate of change* in `open_count` / queue depth instead of absolute age, until someone decides whether those old rows should be cleaned up or excluded at the query level.

## Sanitized sample responses

Captured live against `exchange-backend` on 2026-07-29, IDs/amounts are real production values as of that moment (this is a live exchange, not synthetic data — treat these numbers as a shape reference, not a fixture to hardcode against).

**`GET /api/bot/health`** (captured live 2026-07-30)
```json
{
  "data": {
    "status": "ok",
    "service": "exchange-backend",
    "server_time": "2026-07-30T19:04:08+00:00",
    "server_time_unix": 1785438248,
    "components": {
      "database": { "status": "ok", "latency_ms": 0.79 },
      "matching_engine": { "status": "ok", "latency_ms": 33.67 }
    }
  },
  "meta": { "request_id": "1dcbc582-...", "generated_at": "2026-07-30T19:04:08+00:00", "currency": "IRT", "data_freshness_seconds": 0 }
}
```

**`GET /api/bot/transactions/summary`** (captured live 2026-07-30 — see the data-quality warning above about `oldest_open_age_seconds`)
```json
{
  "data": {
    "as_of": "2026-07-30T19:09:41+00:00",
    "deposits": {
      "by_status": { "pending": 34582, "processing": 1117, "confirmed": 170350, "rejected": 2, "unknown": 0 },
      "open_count": 35699,
      "oldest_open_created_at": "2022-02-01 00:01:50",
      "oldest_open_age_seconds": 141777471
    },
    "withdrawals": {
      "by_status": { "pending": 6129, "verified": 171, "processing": 16888, "completed": 111710, "cancelled": 785 },
      "open_count": 23188,
      "oldest_open_created_at": "2022-06-26 05:41:49",
      "oldest_open_age_seconds": 129232672
    }
  },
  "meta": { "request_id": "893b55ac-...", "generated_at": "2026-07-30T19:09:41+00:00", "currency": "IRT", "data_freshness_seconds": 30 }
}
```
Note the `open_count` values themselves (35,699 open deposits; 23,188 open withdrawals) are large enough that they likely also include a substantial backlog of old/abandoned rows, not all genuinely "pending right now" — the same caveat applies to the counts, not just the age fields.

**`GET /api/bot/withdrawals/pending?limit=1`** (captured live 2026-07-30)
```json
{
  "data": {
    "as_of": "2026-07-30T19:10:00+00:00",
    "count_returned": 1,
    "next_cursor": "49058",
    "items": [
      {
        "withdrawal_id": 49058, "user_id": 1738, "asset": "IRT", "network": "",
        "status": "processing", "process_status": 0,
        "requested_amount": "100000.00000000", "sent_amount": "96000.00000000", "fee": "4000.00000000",
        "destination": "IR31******************9001", "transaction_hash": null,
        "created_at": "2022-06-26 05:41:49", "updated_at": "2022-06-26 05:41:56",
        "age_seconds": 129232672
      }
    ]
  },
  "meta": { "request_id": "fb66ab3a-...", "generated_at": "2026-07-30T19:10:00+00:00", "currency": "IRT", "data_freshness_seconds": 30 }
}
```
`network: ""` is a genuine DB value (empty `asset_withdraw_networks.network_ticker`), confirmed live, not a join bug — seen on IRT (fiat) rows here. Pass `next_cursor` back as `?cursor=49058` to get the next page; this is real keyset pagination (by `id`, oldest-first), not the offset-based `limit` the per-user endpoints use.
Returns **HTTP 200 even when degraded** — always read `data.status` (`ok` | `degraded`), not the status code. A failing component adds `error_code` (`query_failed` | `unreachable` | `unexpected_response`); underlying exception text is deliberately not exposed since it can carry DSNs/credentials. `server_time`/`server_time_unix` let you detect clock drift before it starts causing signature rejections.

**`GET /api/bot/operations?date_from=2026-06-29&date_to=2026-07-29`**
```json
{
  "data": {
    "date_from": "2026-06-29 18:18:31",
    "date_to": "2026-07-29 18:18:31",
    "orders": 261,
    "deposits": 60,
    "withdrawals": 203,
    "pending_withdrawals": 42,
    "failed_deposits": 0,
    "fee_revenue_by_asset": { "USDT": "8.36989817", "IRT": "1995095.77433421", "BTC": "0.00003376" }
  },
  "meta": { "request_id": "d19d7091-...", "generated_at": "2026-07-29T18:18:33+00:00", "currency": "IRT", "data_freshness_seconds": 60 }
}
```

**`GET /api/bot/market/BTC_USDT/summary`**
```json
{
  "data": {
    "market": "BTC_USDT", "is_active": true, "base_asset": "BTC", "quote_asset": "USDT",
    "last": "63836.85000000", "open": "0.00000000", "high": "0.00000000", "low": "0.00000000", "volume": "0.00000000",
    "as_of": "2026-07-29T18:18:43+00:00"
  },
  "meta": { "request_id": "85c3dc56-...", "generated_at": "2026-07-29T18:18:43+00:00", "currency": "IRT", "data_freshness_seconds": 10 }
}
```

**`GET /api/bot/user/{userId}/deposits`** (shape, from source — status enum confirmed in code)
```json
{
  "data": {
    "user_id": 1, "date_from": "2026-06-29 00:00:00", "date_to": "2026-07-29 00:00:00",
    "items": [
      {
        "deposit_id": 4821, "asset": "USDT", "amount": "500.00000000", "net_amount": "499.50000000",
        "status": "confirmed",
        "transaction_hash": "0xa1b2****************c3d4",
        "destination": "0x9f8e****************1a2b",
        "confirmed_at": "2026-07-15 09:12:44", "created_at": "2026-07-15 09:10:02",
        "cost_basis_mark_irt": null
      }
    ]
  },
  "meta": { "request_id": "...", "generated_at": "...", "currency": "IRT", "data_freshness_seconds": 30 }
}
```
Status enum: `rejected` (-1) / `pending` (0) / `confirmed` (1) / `processing` (99) / `unknown` (unmapped code).

**`GET /api/bot/user/{userId}/withdrawals`** (shape, from source)
```json
{
  "data": {
    "user_id": 1, "date_from": "2026-06-29 00:00:00", "date_to": "2026-07-29 00:00:00",
    "items": [
      {
        "withdrawal_id": 9931, "asset": "TRX", "requested_amount": "1000.00000000", "sent_amount": "998.00000000",
        "fee": "2.00000000", "status": "processing",
        "destination": "TXYZ****************9Q1R",
        "transaction_hash": null,
        "created_at": "2026-07-28 14:03:11", "updated_at": "2026-07-28 14:05:00"
      }
    ]
  },
  "meta": { "request_id": "...", "generated_at": "...", "currency": "IRT", "data_freshness_seconds": 30 }
}
```
Status derivation order (first match wins): `cancelled` → `completed` → `processing` → `verified` → `pending`. Note there's no explicit "failure/rejection reason" field on withdrawals yet — status alone doesn't tell you *why* something is stuck, which matters for the withdrawal-slowdown pilot specifically.

## Data dictionary (from source, not invented)

- **Deposit status**: `rejected` / `pending` / `confirmed` / `processing` (see enum above).
- **Withdrawal status**: derived from four boolean flags (`cancelled`, `is_done`, `is_confirmed`, `is_verified`) checked in that priority order — not a single stored enum column.
- **Balance `available`/`blocked`/`total`**: from the matching engine's live balance query (`available` + `freeze` = `total`); not a DB snapshot.
- **`value_irt`**: `total * mark_price_irt`, where mark price is looked up `ASSET_IRT` directly, or synthesized via `ASSET_USDT * USDT_IRT` if no direct pair exists; `null` if neither resolves.
- **PnL**: currently **execution PnL only** (sum of `order_pl.pl_irt`) — the response explicitly flags `"calculation_complete": false` and `"incomplete_reason": "weighted_average_ledger_not_connected"`. Don't treat this as a complete PnL figure.

## OpenAPI/Postman fixes applied in v0.2

- Full response schemas for every endpoint (user summary/balances/trades/pnl previously had none).
- Fixed the invalid `type: "null"` on `cost_basis_mark_irt` → `nullable: true`.
- Added `required` arrays on all response objects and `Meta`.
- `generated_at`/`as_of`/`executed_at` marked `format: date-time` (they're true ISO 8601). `created_at`/`updated_at`/`date_from`/`date_to` are **not** — see "Known timestamp inconsistency" below — left as plain strings with an explicit note rather than falsely typed.
- Full error-response set (400/401/403/404/409/422/429/500/502/503) on every path, one shared `ErrorResponse` schema.
- Security scheme description now documents all four required headers and the exact signing recipe (OpenAPI can't natively express multi-header HMAC, so this is a documented placeholder, not a literal `apiKey` mechanism).
- `limit` query param documented (already implemented server-side: max 100, default 50) on trades/deposits/withdrawals. **Cursor-based pagination is still not implemented** — tracked as a v0.3 item, not fabricated in the spec.
- Postman: no more hardcoded `user_1`/fixed dates (now `{{user_id}}`/`{{date_from}}`/`{{date_to}}` — set at the environment level); secret moved out of collection variables into a private Postman Environment (`bot_secret`, `bot_key_id` — **never export/share this environment**); URL parsing now uses Postman's own `URL` object instead of Node's `url` module; the signed query string is built the same way the server verifies it; added response-time/status/structure tests plus negative tests (missing auth → 401, expired timestamp → 401, replay → 409).

## Known timestamp inconsistency (still open)

`generated_at`/`as_of` use `gmdate('c')` → real ISO 8601 (`2026-07-29T18:18:33+00:00`). `created_at`/`updated_at`/`confirmed_at`/`date_from`/`date_to` come straight from MySQL `DATETIME` columns or `gmdate('Y-m-d H:i:s', ...)` → `2026-07-29 18:18:31`, UTC but not RFC 3339 and with no `Z`/offset marker. Both are documented as-is in `openapi.yaml` rather than papered over. Standardizing everything to `…Z` UTC is a real fix, just not a safe one to make blind — several of these fields are read by other things in `exchange-backend` (the admin panel, possibly the mobile/SPA clients on the equivalent non-bot routes) and changing the format is a cross-cutting change outside this controller, not something to do as a side effect of the bitAgent pilot.

## Not yet built

**Auth hardening still open** (see "Still open on auth" above): revocation/rotation tooling.

**New aggregate/ops endpoints requested for genuine exchange-wide slowdown detection** (the existing endpoints require already knowing which user is affected — fine for investigating a specific report, not for detecting a slowdown in the first place). None of these exist yet; building them needs either a live-schema check I haven't been able to do (see below) or new integration work against services outside `exchange-backend`:

| Endpoint | Data source it would need |
|---|---|
| ~~`GET /api/bot/health`~~ | **Built 2026-07-30** — see endpoint table above |
| ~~`GET /api/bot/transactions/summary`~~ | **Built 2026-07-30** — see endpoint table above and the data-quality warning on `oldest_open_age_seconds` |
| ~~`GET /api/bot/withdrawals/pending`~~ | **Built 2026-07-30**, cursor-paginated by id — see endpoint table above |
| `GET /api/bot/deposits/pending` | Not built yet — same shape as withdrawals/pending above, against the `deposits` table instead; should be a quick follow-up using the same pattern |
| `GET /api/bot/networks/status` | Nothing today exposes per-chain wallet-mon health — needs new endpoints on each `*-wallet-mon` service |
| `GET /api/bot/queues/status` | Kafka consumer-lag isn't exposed anywhere (`core-webhook-handler` consumes but doesn't report lag) |
| `GET /api/bot/workers/status` | No worker/heartbeat concept currently exists in `exchange-backend` or the wallet services as inspected |
| `GET /api/bot/markets` | `MarketController` already has the underlying data (`/api/market/list`) — mostly a matter of adding a bot-auth'd wrapper |
| `GET /api/bot/market/{market}/orderbook-summary` | `/api/orderbook/depth/{MARKET}` already exists non-bot-auth'd — same, wrapper work |
| `GET /api/bot/liabilities` | `exchange-core-mysql`'s `trade_log.slice_balance_<unix_ts>` snapshot tables (confirmed via `market-monitor`'s `calc_user_totals7.py`) — **schema not verified live**, a `SHOW TABLES`/`DESCRIBE` was blocked by this session's permission policy as a live-prod DB read; needs either that check or you supplying the schema |
| `GET /api/bot/treasury` | No aggregation point exists at all — would need new integration against every `*-wallet-mon`/`*-wallet-gen` service's own DB |
| `GET /api/bot/reconciliation` | Depends on both `liabilities` and `treasury` existing first |

Per-withdrawal fields still missing regardless of endpoint (**confirmation count**, **required confirmations**, **status reason/code**, **retry count**, **worker/queue reference**): not present in the `Withdraw` model as queried today — needs either a schema check or a different data source per field.

**Not derivable from this codebase at all**: sandbox/staging environment, business thresholds (latency, spread, hot-wallet min/max, reconciliation tolerance), incident history, alert channel (Telegram/Slack/email). These are inputs only you can supply.

**Recommended next milestone** (matches the reviewer's suggestion): pick a subset of the six buildable-now endpoints above (health, transactions/summary, pending withdrawals/deposits, markets, orderbook-summary) and confirm whether the liabilities schema check can be unblocked, before writing any of the wallet-service integration work.
