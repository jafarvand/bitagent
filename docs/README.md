# bitAgent read-only pilot — exchange-backend

Companion to `openapi.yaml` and `bitAgent.postman_collection.json` in this folder.

## Status vs. the XIMA contract

`exchange-side-requirements.md` (repo root of `data/`) is the upstream contract for turning this pilot into a real bitAgent/XIMA integration — P0/P1/P2 priorities, a full response-envelope spec, scopes, and ~2 dozen endpoints across ops/markets/treasury/AML/security/support. What's in this folder implements a slice of that contract's **P0 items 1, 2, 3 (partial), 4 (partial), 5 (partial — liabilities + treasury wallet/IRT assets, not full reconciliation), 7 (partial), and 8** — auth, health, transaction/ops endpoints, aggregate liabilities, treasury asset totals, the v0.4 response envelope, and (as of v0.6) an isolated staging sandbox with synthetic fixtures. P0 item 6 (AML/security/support), the reconciliation portion of item 5, and everything in P1/P2, are not built; see "Not yet built" at the bottom, which is organized to match that document's structure.

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
4. Secrets live in `.env.bitagent` at the repo root as `EXCHANGE_BOT_SERVICE_KEYS=key_id:secret:scope1|scope2,key_id2:secret2` (comma-separated entries — add a new one to rotate without downtime, remove one to revoke immediately), loaded into the `exchange-backend` container via `env_file` in `docker-compose.yml`. **Not committed to the config file itself, not printed in this doc.** A container recreate (`docker compose up -d exchange-backend`) is required after editing `.env.bitagent` for the new keys to take effect.
5. **Scopes (v0.4, extended through v0.8)**, per `exchange-side-requirements.md`'s authorization table: `health:read`, `operations:read`, `transactions:read`, `markets:read`, `ledger-summary:read`, `wallet-summary:read` are enforced on the endpoints that map cleanly to that catalog (`health`, `operations`, `transactions/summary`, `withdrawals/pending` and `deposits/pending` → `transactions:read`, `market/{id}/summary`, `ledger/liabilities` → `ledger-summary:read`, `treasury/assets` → `wallet-summary:read`). A key's scope segment is optional — omitting it (or using the pre-v0.4 `key_id:secret` two-field format) grants unrestricted access; that's a backward-compat path for existing keys, not the recommended shape for a new one. The legacy per-user endpoints (`userSummary`, `balances`, `trades`, `deposits`, `withdrawals`, `pnl`) aren't in the contract's scope catalog and stay open to any authenticated key regardless of scopes — inventing a scope name for them would be guessing at product intent. Insufficient scope → 403 `scope_denied`. Verified live 2026-08-02: a key scoped to `health:read` only succeeded on `/health` and got `scope_denied` on `/operations`, `/deposits/pending`, and `/ledger/liabilities`; the existing unscoped production key was unaffected throughout.
6. Optional IP allowlist via `EXCHANGE_BOT_ALLOWED_IPS` (comma-separated) — **configured as of 2026-07-30** with the bitAgent host's egress IP(s) plus `127.0.0.1` for local testing. Update this file directly (`.env.bitagent`) and recreate `exchange-backend` when the bitAgent's egress IP changes.
7. Per-key rate limiting: `EXCHANGE_BOT_RATE_LIMIT_PER_MINUTE` (default 120), file-counter based under `temp/bot_ratelimit/`. Exceeding it returns 429.
8. Every auth outcome (success, bad signature, IP denied, scope denied, rate limited, replay, config missing) is logged via `error_log` — visible in `docker compose logs exchange-backend`, tagged `[bot-auth]` with `event`, `key_id`, `request_id`, `ip`, `path`.
9. All failures return a structured JSON error — `code`, `message`, `request_id`, plus (as of v0.4) `retryable` (boolean) and `retry_after_seconds` (only set, to 60, on a 429) and `details` (reserved, always `{}` today) — with the appropriate status: 503 config missing, 403 IP/scope denied, 429 rate limited, 401 bad/missing signature, 409 replay.

There is no write, trade, transfer, or withdrawal action reachable through this controller — an earlier `cancelOrderAction` was removed before routing anything live.

**Still open on auth:** key revocation/rotation is supported by the `EXCHANGE_BOT_SERVICE_KEYS` format described above, but there's no tooling around it yet (it's a manual `.env.bitagent` edit + container recreate) — fine for a single pilot key, would want a real process before onboarding multiple consumers. `X-Tenant-ID` (for a credential spanning more than one tenant) isn't implemented — moot today since this is a single-tenant exchange, see the envelope section below.

## Response envelope (v0.4 — breaking change from v0.3's `{data, meta}` shape)

Every successful response now matches `exchange-side-requirements.md` §2.3's envelope, built centrally in `successResponse()` so every endpoint gets it automatically:

```json
{
  "schema": {"name": "transactions.summary", "version": "1.0.0"},
  "tenant_id": "bitimen",
  "source_id": "exchange-backend-mysql",
  "owner": "exchange-backend-team",
  "observed_at": "2026-08-02T09:09:41+00:00",
  "generated_at": "2026-08-02T09:09:41+00:00",
  "freshness_sla_seconds": 30,
  "data_class": "internal",
  "lineage": ["exchange-backend-mysql"],
  "quality": {"complete": true, "warnings": []},
  "request_id": "893b55ac-...",
  "data": { }
}
```

Notes on what's real vs. placeholder here:
- `tenant_id` is a **fixed constant** (`bitimen`) — this is a single-tenant exchange, there's no actual multi-tenant lookup behind it. If that ever changes, this needs to become real per-credential data, not a hardcoded string.
- `owner` is a single global value from `EXCHANGE_BOT_OWNER` (default `exchange-backend-team`), not yet split per-endpoint the way the contract implies it eventually should be (e.g. AML endpoints owned by compliance) — moot today since those endpoints don't exist yet.
- `observed_at` and `generated_at` are **always identical** — every endpoint reads live at request time with no separate capture step, so there's no real lag to report. This stops being true the moment any endpoint starts serving from a cache or snapshot table.
- `quality` is a **static placeholder** (`{"complete": true, "warnings": []}` on every response) — no endpoint actually detects or flags partial results yet.
- `freshness_sla_seconds` is the old `data_freshness_seconds` renamed to match the contract's field name — still an informal per-endpoint cache-staleness hint, not a monitored SLA.
- `request_id` is kept at the top level in addition to the contract's fields — not part of the spec, kept for `[bot-auth]` log correlation.
- `schema.name` uses dot notation per endpoint (`health`, `operations`, `transactions.summary`, `withdrawals.pending`, `deposits.pending`, `market.summary`) for the 6 endpoints that map to the contract's catalog; the legacy per-user endpoints fall back to their raw action name (e.g. `userSummary`) since they predate the contract.

Error responses also gained fields — see auth point 9 above.

## Available read-only endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/bot/health` | Backend + dependency health (database, matching engine) with per-component latency |
| GET | `/api/bot/transactions/summary` | Exchange-wide open deposit/withdrawal counts by status, right now (not date-ranged) |
| GET | `/api/bot/withdrawals/pending` | All in-flight withdrawals, exchange-wide, oldest first, cursor-paginated |
| GET | `/api/bot/deposits/pending` | All in-flight deposits, exchange-wide, oldest first, cursor-paginated |
| GET | `/api/bot/ledger/liabilities` | Aggregate customer liability per asset, from the matching engine's own balance snapshots |
| GET | `/api/bot/treasury/assets` | Exchange-controlled crypto wallet totals (by asset/custody class) + company IRT bank balance |
| GET | `/api/bot/operations` | Aggregated deposit/withdrawal/order counts + fee revenue for a date range |
| GET | `/api/bot/market/{marketIdentifier}/summary` | Single market ticker/status (e.g. `BTC_USDT`) |
| GET | `/api/bot/user/{userId}/summary` | Account status, KYC level, order counts |
| GET | `/api/bot/user/{userId}/balances` | Per-asset available/blocked/total + IRT valuation |
| GET | `/api/bot/user/{userId}/trades` | Executed trades in a date range |
| GET | `/api/bot/user/{userId}/deposits` | Deposit records in a date range (tx hash/destination masked) |
| GET | `/api/bot/user/{userId}/withdrawals` | Withdrawal records in a date range (tx hash/destination masked) |
| GET | `/api/bot/user/{userId}/pnl` | Execution PnL in a date range (partial — cost-basis ledger not connected yet) |

**Known gap:** none of these give aggregated **treasury** (exchange hot-wallet balances) data — see "Not yet built" below. (**Liabilities** is now built — see the endpoint table above.)

**⚠️ Data-quality trap — read before wiring up alerts:** `transactions/summary`, `withdrawals/pending`, and `deposits/pending` all surface `oldest_open_*`/`age_seconds`. Live on 2026-07-30 (deposits confirmed live again 2026-08-02), the oldest "open" deposit was from **2022-02-01** and the oldest "open" withdrawal from **2022-06-26** — both over 4 years old. These are almost certainly stale/abandoned rows never properly closed out in the database, not an active incident. **Do not alert directly on the raw age value** — it will fire immediately and permanently. Either cap what counts as "genuinely pending" at some reasonable ceiling (a business decision, not made here), or alert on the *rate of change* in `open_count` / queue depth instead of absolute age, until someone decides whether those old rows should be cleaned up or excluded at the query level.

## Sanitized sample responses

Captured live against `exchange-backend` on 2026-08-02 (v0.4 envelope), IDs/amounts are real production values as of that moment (this is a live exchange, not synthetic data — treat these numbers as a shape reference, not a fixture to hardcode against). The first sample shows the full envelope; the rest omit the repeated wrapper fields (`"…": "envelope fields as above"`) and show only what differs.

**`GET /api/bot/health`**
```json
{
  "schema": {"name": "health", "version": "1.0.0"},
  "tenant_id": "bitimen",
  "source_id": "exchange-backend",
  "owner": "exchange-backend-team",
  "observed_at": "2026-08-02T09:22:03+00:00",
  "generated_at": "2026-08-02T09:22:03+00:00",
  "freshness_sla_seconds": 0,
  "data_class": "internal",
  "lineage": ["exchange-backend"],
  "quality": {"complete": true, "warnings": []},
  "request_id": "9abe07a2-5bc9-4ada-b5b7-b358880f21e3",
  "data": {
    "status": "healthy",
    "service": "exchange-backend",
    "environment": "production",
    "server_time": "2026-08-02T09:22:03+00:00",
    "server_time_unix": 1785662523,
    "components": {
      "database": { "name": "exchange-backend-mysql", "type": "mysql", "status": "healthy", "latency_ms": 0.51 },
      "matching_engine": { "name": "exchange-core", "type": "matching-engine", "status": "healthy", "latency_ms": 12.13 }
    }
  }
}
```
Returns **HTTP 200 even when degraded** — always read `data.status` (`healthy` | `degraded` | `maintenance`), not the status code. `maintenance` reflects the same `system_maintenance_mode` setting toggled from exchange-admin, checked live on every call. A failing component adds `error_code` (`query_failed` | `unreachable` | `unexpected_response`); underlying exception text is deliberately not exposed since it can carry DSNs/credentials. `server_time`/`server_time_unix` let you detect clock drift before it starts causing signature rejections. Not implemented: request/error rates, latency percentiles, CPU/memory/disk saturation, uptime, deployed version — omitted rather than fabricated.

**`GET /api/bot/transactions/summary`** (see the data-quality warning above about `oldest_open_age_seconds`)
```json
{
  "…": "envelope fields as above",
  "schema": {"name": "transactions.summary", "version": "1.0.0"},
  "data": {
    "as_of": "2026-08-02T09:22:04+00:00",
    "deposits": {
      "by_status": { "pending": 34582, "processing": 1117, "confirmed": 170354, "rejected": 2, "unknown": 0 },
      "open_count": 35699,
      "oldest_open_created_at": "2022-02-01 00:01:50",
      "oldest_open_age_seconds": 142001414
    },
    "withdrawals": {
      "by_status": { "pending": 6130, "verified": 175, "processing": 16884, "completed": 111719, "cancelled": 785 },
      "open_count": 23189,
      "oldest_open_created_at": "2022-06-26 05:41:49",
      "oldest_open_age_seconds": 129456615
    }
  }
}
```
Note the `open_count` values themselves (35,699 open deposits; 23,189 open withdrawals) are large enough that they likely also include a substantial backlog of old/abandoned rows, not all genuinely "pending right now" — the same caveat applies to the counts, not just the age fields.

**`GET /api/bot/withdrawals/pending?limit=1`**
```json
{
  "…": "envelope fields as above",
  "schema": {"name": "withdrawals.pending", "version": "1.0.0"},
  "data": {
    "as_of": "2026-08-02T09:22:04+00:00",
    "count_returned": 1,
    "next_cursor": "49058",
    "items": [
      {
        "withdrawal_id": 49058, "user_id": 1738, "asset": "IRT", "network": "",
        "status": "processing", "process_status": 0,
        "requested_amount": "100000.00000000", "sent_amount": "96000.00000000", "fee": "4000.00000000",
        "destination": "IR31******************9001", "transaction_hash": null,
        "created_at": "2022-06-26 05:41:49", "updated_at": "2022-06-26 05:41:56",
        "age_seconds": 129456615
      }
    ]
  }
}
```
`network: ""` is a genuine DB value (empty `asset_withdraw_networks.network_ticker`), confirmed live, not a join bug — seen on IRT (fiat) rows here. Pass `next_cursor` back as `?cursor=49058` to get the next page; this is real keyset pagination (by `id`, oldest-first), not the offset-based `limit` the per-user endpoints use.

**`GET /api/bot/deposits/pending?limit=1`**
```json
{
  "…": "envelope fields as above",
  "schema": {"name": "deposits.pending", "version": "1.0.0"},
  "data": {
    "as_of": "2026-08-02T09:30:29+00:00",
    "count_returned": 1,
    "next_cursor": "83656",
    "items": [
      {
        "deposit_id": 83656, "user_id": 368, "asset": "IRT", "network": "کارتهای شتاب",
        "status": "pending", "collect_status": 2,
        "amount": "8000000.00000000", "net_amount": "0.00000000",
        "destination": null, "transaction_hash": null,
        "created_at": "2022-02-01 00:01:50", "updated_at": "2022-02-01 00:01:51",
        "age_seconds": 142001919
      }
    ]
  }
}
```
`network` here is a **human-readable name**, not a short ticker like withdrawals — `کارتهای شتاب` is Persian for "Shetab cards," Iran's domestic bank-card network, confirming `asset_deposit_networks.name` (unlike `asset_withdraw_networks`, this table has no `network_ticker` column, so there's genuinely no ASCII short form to fall back to). `destination: null` here (rather than a masked string) reflects a real absence of an on-chain deposit address on this fiat/IRT row, not a masking failure. `collect_status` is the deposit-side analog of withdrawals' `process_status` — same treatment: raw integer exposed, free-text `collect_result` deliberately withheld (unconfirmed sensitivity, same reasoning as withdrawals).

**`GET /api/bot/ledger/liabilities`** (captured live 2026-08-02 — real production data, truncated to a few assets here; the real response has 133)
```json
{
  "…": "envelope fields as above",
  "schema": {"name": "ledger.liabilities", "version": "1.0.0"},
  "source_id": "exchange-core-mysql",
  "data": {
    "ledger_snapshot_at": "2026-08-02T10:05:15+00:00",
    "asset_count": 133,
    "negative_balance_count": 0,
    "liabilities": [
      { "asset": "BTC", "available": "19.27460387", "locked": "0.00840996", "total": "19.28301383" },
      { "asset": "USDT", "available": "10070106778.92298126", "locked": "831.02699584", "total": "10070107609.94997787" },
      { "asset": "IRT", "available": "7966473050387.38574219", "locked": "196381016.03881183", "total": "7966669431403.42480469" }
    ]
  }
}
```
Response time: ~270ms (single aggregate query, no matching-engine RPC calls involved). `ledger_snapshot_at` is the actual snapshot table's timestamp — observed live snapshots ~15 minutes apart, not a documented SLA, so treat this endpoint as eventually-consistent, not real-time. **Deliberately no IRT valuation per asset** — see the endpoint's own OpenAPI description for why (130+ assets × up to 3 RPC calls each per `getIrtMarkPrice` is not a request anyone should wait on). Cross-checked against the staging synthetic fixtures (0.05+0.012=0.062 BTC available, one deliberately-negative IRT row correctly isolated into `negative_balance_count: 1` and folded into the aggregate rather than dropped) — the arithmetic is exactly right, not just plausible-looking.

**`GET /api/bot/treasury/assets`** (captured live against **staging** 2026-08-02, synthetic fixture data — production returns the same shape but with real wallets/IRT total; see "Not verified against production" note in the v0.8 changelog)
```json
{
  "…": "envelope fields as above",
  "schema": {"name": "treasury.assets", "version": "1.0.0"},
  "source_id": "exchange-backend-mysql+jibit-cobank",
  "quality": {"complete": false, "warnings": [
    "treasury wallet #2 (ETH) last refresh failed: RPC timeout after 3 retries",
    "company bank account IR72******************8867 balance fetch failed: could not obtain jibit cobank access token"
  ]},
  "data": {
    "as_of": "2026-08-02T11:45:31+00:00",
    "crypto": {
      "assets": [
        { "asset": "BNB", "by_custody_class": { "hot": "1.50000000" }, "total": "1.50000000" },
        { "asset": "BTC", "by_custody_class": { "cold": "0.75000000" }, "total": "0.75000000" },
        { "asset": "ETH", "by_custody_class": { "hot": "0.02000000" }, "total": "0.02000000" },
        { "asset": "USDT", "by_custody_class": { "hot": "5000.00000000" }, "total": "5000.00000000" }
      ],
      "wallets": [
        { "wallet_id": 3, "label": "Staging BTC cold wallet", "network": "BTC", "native_asset": "BTC", "custody_class": "cold", "is_active": true, "address": "bc1q**********************************1234", "native_balance": "0.75000000", "last_refreshed_at": "2026-08-01 11:31:37", "last_refresh_error": null, "tokens": [] },
        { "wallet_id": 1, "label": "Staging BSC hot wallet", "network": "BSC", "native_asset": "BNB", "custody_class": "hot", "is_active": true, "address": "0xSt*********************************3456", "native_balance": "1.50000000", "last_refreshed_at": "2026-08-02 11:21:37", "last_refresh_error": null, "tokens": [
          { "symbol": "USDT", "balance": "5000.00000000", "last_refreshed_at": "2026-08-02 11:21:37", "last_refresh_error": null }
        ] },
        { "wallet_id": 2, "label": "Staging ETH hot wallet (stale)", "network": "ETH", "native_asset": "ETH", "custody_class": "hot", "is_active": true, "address": "0xSt*********************************3456", "native_balance": "0.02000000", "last_refreshed_at": "2026-07-28 11:31:37", "last_refresh_error": "RPC timeout after 3 retries", "tokens": [] }
      ]
    },
    "fiat": {
      "total_irt": null,
      "accounts": [
        { "account_id": 1, "iban_masked": "IR72******************8867", "balance_irt": null, "fetched_at": null, "error": "could not obtain jibit cobank access token" }
      ]
    }
  }
}
```
Two duplicate active `company_bank_accounts` rows sharing one IBAN (a real pattern also observed in production) correctly collapse into a single `fiat.accounts[]` entry; a third inactive row is excluded entirely. `fiat.total_irt: null` and the Jibit-related `error`/warning here are staging's intended behavior (its `jibitCobank` config points at a deliberately unreachable host) — in production this field is a live IRT total. The stale ETH wallet's `last_refresh_error` surfaces both on its own wallet row and as a top-level `quality.warnings` entry, while every other row still returns normally (`quality.complete: false`, not a failed request). Crypto balances reflect exchange-admin's Treasury page, which has no cron auto-refresh — `last_refreshed_at` can be arbitrarily stale.

**`GET /api/bot/operations?date_from=2026-07-03&date_to=2026-08-02`**
```json
{
  "…": "envelope fields as above",
  "schema": {"name": "operations", "version": "1.0.0"},
  "data": {
    "date_from": "2026-07-02 19:30:00",
    "date_to": "2026-08-01 19:30:00",
    "orders": 253,
    "deposits": 65,
    "withdrawals": 212,
    "pending_withdrawals": 42,
    "failed_deposits": 0,
    "fee_revenue_by_asset": { "IRT": "2001275.19136659", "USDT": "7.43113311", "XRP": "1.10840494" }
  }
}
```

**`GET /api/bot/market/BTC_USDT/summary`**
```json
{
  "…": "envelope fields as above",
  "schema": {"name": "market.summary", "version": "1.0.0"},
  "source_id": "exchange-core",
  "data": {
    "market": "BTC_USDT", "is_active": true, "base_asset": "BTC", "quote_asset": "USDT",
    "last": "63836.85000000", "open": "0.00000000", "high": "0.00000000", "low": "0.00000000", "volume": "0.00000000",
    "as_of": "2026-08-02T09:22:06+00:00"
  }
}
```

**`GET /api/bot/user/{userId}/deposits`** (shape, from source — status enum confirmed in code; not re-captured live this pass, same as v0.3 except the envelope)
```json
{
  "…": "envelope fields as above",
  "schema": {"name": "deposits", "version": "1.0.0"},
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
  }
}
```
Status enum: `rejected` (-1) / `pending` (0) / `confirmed` (1) / `processing` (99) / `unknown` (unmapped code).

**`GET /api/bot/user/{userId}/withdrawals`** (shape, from source; not re-captured live this pass, same as v0.3 except the envelope)
```json
{
  "…": "envelope fields as above",
  "schema": {"name": "withdrawals", "version": "1.0.0"},
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
  }
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

## Changes applied in v0.4 (this pass — E1 slice of `exchange-side-requirements.md`)

- **Breaking**: the response envelope changed from `{data, meta}` to the full contract shape (`schema`, `tenant_id`, `source_id`, `owner`, `observed_at`, `generated_at`, `freshness_sla_seconds`, `data_class`, `lineage`, `quality`, `request_id`, `data`) — see "Response envelope" section above. Every `openapi.yaml` response schema converted to `allOf: [Envelope, {data: ...}]`; every Postman test assertion updated to match; every sample response in this doc recaptured live.
- Error envelope gained `retryable`, `retry_after_seconds`, `details`.
- Per-key **scopes** added (`health:read`, `operations:read`, `transactions:read`, `markets:read`), backward-compatible with unscoped keys. Verified live: a `health:read`-only key succeeded on `/health`, got 403 `scope_denied` on `/operations`.
- `/health`: `status` renamed `ok`→`healthy` (contract's enum is `healthy`/`degraded`/`unavailable`/`maintenance` — this implementation only ever reports the first three, see the endpoint's own doc note on why `unavailable` isn't emitted); added `maintenance` detection via the same `system_maintenance_mode` setting exchange-admin already toggles; added `name`/`type` to each component and `environment` to the response.
- OpenAPI bumped to `0.4.0-pilot`.

## Changes applied in v0.5

- Built `GET /api/bot/deposits/pending` — cross-user, cursor-paginated, oldest-first, mirroring `withdrawals/pending`. Scoped to `transactions:read`, verified live (correct results, correct pagination, and correct scope denial for a `health:read`-only test key).
- Discovered live (not assumed): `asset_deposit_networks` has no `network_ticker` column like the withdraw side does, so `network` on this endpoint is a human-readable name (observed in Persian for IRT/fiat rows) rather than a short ticker — documented as a genuine schema asymmetry, not unified into a fake shared shape.
- `destination: null` (rather than a masked placeholder) confirmed as a real absence of a deposit address on old fiat rows, not a masking bug.
- OpenAPI bumped to `0.5.0-pilot`.

## Staging environment (v0.6 — P0 item 8, "sanitized replay dataset and non-production test tenant")

**`https://staging-devapi.zekabot.com`** — a genuinely isolated sandbox, built 2026-08-02.

**Isolation, not just a different label:**
- **Separate MySQL container** (`bitagent-staging-mysql`, `mysql:5.7`), own root credentials, own Docker network (`bitagent-staging-network`, marked `internal: true` — no route out to the internet or to production's `core-network`).
- **100% synthetic data.** Nothing here was copied from production, sanitized or otherwise. The current schema is a hand-built subset covering only what `BotController` actually queries (`deposits`, `withdraws`, `users`, `user_orders`, `user_logs`, `asset_deposit_networks`, `asset_withdraw_networks`, `income_details`, `order_pl`, `markets`, `assets`, `settings`) — not a full copy of production's schema.
- **Separate bot-auth key** (`bitagent-staging-01`, distinct secret from the production key in `.env.bitagent`) — per the contract's "read and action credentials must never share a key or scope," and per plain good sense: a staging key leaking is a non-event, so it shouldn't be able to touch anything that isn't also a non-event.
- **IP allowlist**: `159.69.109.189` + `127.0.0.1`, configured 2026-08-02 (same bitAgent host as production's allowlist). Update `.env.bitagent-staging` and recreate `exchange-backend-staging` if that changes.
- **No matching-engine replica, deliberately.** `rpcBaseUri` points at a hostname (`staging-no-matching-engine`) that doesn't exist. Endpoints that depend on it (`market/{id}/summary`, `user/{id}/balances`, `user/{id}/trades`) reliably fail — this is intentional, it's the "dependency unreachable" scenario, not a bug to fix.

**Fixture scenario matrix**, covering exchange-side-requirements.md §9's replay-package requirement (`config/exchange-backend-staging/init-db/01-schema-and-fixtures.sql`, fully commented inline): normal · warning (recent pending) · critical (multi-day-old pending) · stale (mirrors the real ~4-year-old abandoned rows found in production, so the age-alerting trap reproduces against synthetic data too) · missing (a network FK pointing at a nonexistent row → `network: null`, distinct from production's observed `network: ""`) · conflicting (a deposit where `net_amount > amount`; a withdrawal marked both `cancelled` and `is_done`) · duplicate (two rows, identical `tx_hash`) · out-of-order (`modified_at` earlier than `created_at`) · partial-failure (an `is_success` code the API's own status map doesn't recognize, landing in the `unknown` bucket).

**A real bug this environment found on its first real test**, not a staging-specific issue: `market/{id}/summary` threw an uncaught `PDOException` straight to the client with no JSON envelope (a missing `markets` table, in this case — but the underlying gap is that **any** uncaught exception in any bot action bypassed the error envelope entirely). Fixed in `Rest\Module.php`'s `dispatch:beforeException` handler, scoped strictly to `controller === 'bot'` so it can't change behavior for any of the other Rest controllers used by production clients — forwards to a new `BotController::internalErrorAction()` that returns the standard structured 500, logs the real exception server-side via `error_log`, never exposes it. Verified live: production's existing 404/200 behavior on unrelated routes unaffected; the bot API now returns `{"error":{"code":"internal_error",...}}` instead of a raw PDO message.

**A second, deeper issue this surfaced, fixed 2026-08-02**: `market/{id}/summary`'s (and `balances`'/`trades`') existing code already anticipates the matching engine being down (`if (!$status->success) { return 502 ...; }`), but `Core\Plugin\JsonRPC`'s methods don't catch connection failures — they let Guzzle throw instead of returning a `{success: false}` result, so that graceful path never actually triggered, in staging *or* production during a real `exchange-core` outage; it fell through to the generic 500 `internal_error` above instead. Fixed **without touching `JsonRPC` itself** (still a shared class used well beyond this controller — changing it directly stays out of scope): added `BotController::callRpc()`, a wrapper that catches the exception right at each call site and synthesizes the same `{success: false}` shape `JsonRPC` already returns for a soft failure, so every existing `if (!$x->success)` check downstream just works unmodified. Verified live against staging (where the matching engine is guaranteed unreachable): `market/{id}/summary` → 502 `market_service_failed`, `balances` → 502 `balance_service_failed`, `trades` → 502 `trade_history_failed`, none hitting the generic-500 path anymore. Production re-verified unaffected (both endpoints still 200 against the real matching engine).

**Getting access**: ask for the `bitagent-staging-01` secret the same way as the production one — same rule applies, it won't be pasted into chat; run a `!`-prefixed command yourself to pull it from `.env.bitagent-staging` on this host, or ask for a fresh key to be generated.

## Changes applied in v0.7

- **Staging IP allowlist closed**: `159.69.109.189` + `127.0.0.1` (was previously open to any correctly-signed request). Verified: this shell's own non-allowlisted IP now correctly gets 403.
- **Built `GET /api/bot/ledger/liabilities`** — P0 item 5 (partial: liabilities only, not treasury/reconciliation/wallets). Schema check explicitly authorized by the user this session (`DESCRIBE` on `exchange-core-mysql.trade_log.slice_balance_<unix_ts>`) — confirmed columns `id`/`user_id`/`asset`/`t` (1=available, 2=frozen)/`balance`, matching `JsonRPC::balance_query()`'s available/freeze split. No fixed table name: resolved dynamically every request (latest `slice_balance_<unix_ts>`, excluding the `_example` template table), the same approach `market-monitor`'s `calc_user_totals7.py` already uses. Second MySQL connection added (`config/exchange-backend/html/config/conf.d/tradelog_database.php`, `tradeLogDatabase` config key) — `exchange-core-mysql` is already reachable from `exchange-backend` over `core-network`, no network changes needed. Scoped to `ledger-summary:read`.
- Deliberately **not implemented**: IRT valuation per asset (130+ distinct assets observed live × up to 3 matching-engine RPC calls each via `getIrtMarkPrice` would mean hundreds of round-trips per request — returning raw totals instead of building something that risks timing out).
- Staging got a synthetic `trade_log_staging` DB (`config/exchange-backend-staging/init-db/02-tradelog-fixtures.sql`) with the same `slice_balance_<unix_ts>` shape, including one deliberately negative balance to exercise `negative_balance_count`. Verified the aggregation math is exactly right against these fixtures, not just plausible-looking.
- OpenAPI bumped to `0.7.0-pilot`.

## Changes applied in v0.8

- **Built `GET /api/bot/treasury/assets`** — P0 item 5, treasury slice (liabilities was built in v0.7). Two sources combined into one response: (1) exchange-admin's `treasury_wallets`/`treasury_wallet_tokens` tables (already on `exchange-backend-mysql`, no new DB connection needed), aggregated by `(asset, custody_class)` where custody_class is `hot`/`cold` — the only two values `wallet_type` ever holds, so the contract's fuller warm/custodian/pending/restricted taxonomy isn't representable and isn't attempted; (2) a live company-wide IRT total via the same Jibit Co-Bank integration exchange-admin's Accounting page uses (`tokens/generate` auth, ~9h token cache / 30s on failure; `accounts/{iban}/balance`, 60s cache — both in the shared `temp_data` table, same cache keys as exchange-admin, so both apps' caches are shared). Scoped to `wallet-summary:read`.
- **Real bug found and fixed before this could even run**: `BotController.php` referenced `Shared\Model\TreasuryWallet` / `TreasuryWalletToken`, but those model classes never actually existed in `exchange-backend` — only exchange-admin has them. First live call fataled with `Class 'Shared\Model\TreasuryWallet' not found`. Added `apps/Shared/Model/TreasuryWallet.php` and `TreasuryWalletToken.php` as faithful copies of exchange-admin's originals (same table names, same `hasMany('tokens')`/`belongsTo('wallet')` relations the controller already assumed). Lesson for next time: when a new bot endpoint is designed against a table/model that originates in exchange-admin's codebase, confirm the model file actually exists in exchange-backend too — referencing the schema isn't the same as having the class.
- **Data-quality quirk found and handled**: production's `company_bank_accounts` has duplicate active rows sharing the same IBAN (ids 3 and 6, both `IR460190000000219708926000`), which would double-count the IRT total if summed naively. `treasuryAssetsAction()` dedupes by IBAN before calling Jibit. Verified against staging fixtures deliberately seeded with the same duplicate-IBAN pattern: 2 active rows sharing one IBAN correctly collapsed to 1 `fiat.accounts[]` entry, and a 3rd inactive row correctly excluded.
- **First real use of `quality.warnings`** (the field existed in the envelope since v0.4 but was always `[]` until now): a wallet/token with a `last_refresh_error`, or a bank account whose Jibit balance fetch fails, doesn't fail the request — it's reported as a row-level `error`/`last_refresh_error` plus a matching entry in `quality.warnings` (`quality.complete: false`), while every other row still returns. `successResponse()` gained a third `$warnings` parameter (defaults to `[]`, so no other call site needed changes).
- **Manual-refresh-only staleness caveat**: exchange-admin's Treasury page has no cron auto-refresh — an admin clicks "Refresh"/"Refresh all" to update `balance_native`/token `balance`. `last_refreshed_at` can therefore be arbitrarily stale; check it per wallet rather than trusting `freshness_sla_seconds`.
- Staging got fixtures for all three tables this endpoint touches (`config/exchange-backend-staging/init-db/03-treasury-fixtures.sql`): 3 treasury wallets (1 healthy hot + token, 1 stale/errored hot, 1 healthy cold) and 3 `company_bank_accounts` rows (2 sharing one IBAN, 1 inactive) — plus a `temp_data` table (needed for the Jibit cache, initially missing from the fixture file and added once the live test surfaced it). Staging's `jibitCobank` config points at a deliberately unreachable host, so `fiat.total_irt` is always `null` there by design — that's the intended "fiat source unreachable" scenario, not a bug.
- Verified live against staging 2026-08-02: full response shape confirmed correct — asset aggregation math, custody-class split, stale-wallet warning surfaced in both the wallet row and `quality.warnings`, IBAN dedup (2 duplicate rows → 1 account, inactive row excluded), address/IBAN masking, and graceful `fiat.total_irt: null` degradation with a `could not obtain jibit cobank access token` warning.
- **Not verified against production in this pass**: a live production call exercises the real Jibit Co-Bank API with real credentials; that request was blocked by this environment's own tooling safeguards (same restriction hit earlier in the session when testing other real-external-API paths) and wasn't force-worked-around. The one real `treasury_wallets` row in production (a BSC hot wallet) was confirmed to exist via a prior read-only `SELECT`, but the endpoint's real end-to-end production response — in particular the real `fiat.total_irt` — is still unconfirmed. Do this before calling `treasury/assets` fully production-ready.
- OpenAPI bumped to `0.8.0-pilot`.

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
| ~~`GET /api/bot/deposits/pending`~~ | **Built 2026-08-02**, cursor-paginated by id, same pattern as withdrawals/pending — see endpoint table above |
| `GET /api/bot/networks/status` | Nothing today exposes per-chain wallet-mon health — needs new endpoints on each `*-wallet-mon` service |
| `GET /api/bot/queues/status` | Kafka consumer-lag isn't exposed anywhere (`core-webhook-handler` consumes but doesn't report lag) |
| `GET /api/bot/workers/status` | No worker/heartbeat concept currently exists in `exchange-backend` or the wallet services as inspected |
| `GET /api/bot/markets` | `MarketController` already has the underlying data (`/api/market/list`) — mostly a matter of adding a bot-auth'd wrapper |
| `GET /api/bot/market/{market}/orderbook-summary` | `/api/orderbook/depth/{MARKET}` already exists non-bot-auth'd — same, wrapper work |
| ~~`GET /api/bot/ledger/liabilities`~~ | **Built 2026-08-02** — schema verified live (`DESCRIBE` on `exchange-core-mysql.trade_log`, explicitly authorized this session), scoped to `ledger-summary:read` — see endpoint table above |
| ~~`GET /api/bot/treasury/assets`~~ | **Built 2026-08-02**, as `treasury/assets` — sourced from exchange-admin's `treasury_wallets`/`treasury_wallet_tokens` (not the originally-envisioned per-chain `*-wallet-mon` aggregation, which still doesn't expose anything bot-readable) plus a live Jibit Co-Bank IRT total, scoped to `wallet-summary:read` — see endpoint table above |
| `GET /api/bot/reconciliation` | Both `liabilities` and `treasury/assets` now exist; reconciliation (comparing the two, plus flagging discrepancies) is still not built |

Per-withdrawal fields still missing regardless of endpoint (**confirmation count**, **required confirmations**, **status reason/code**, **retry count**, **worker/queue reference**): not present in the `Withdraw` model as queried today — needs either a schema check or a different data source per field.

**Not derivable from this codebase at all**: business thresholds (latency, spread, hot-wallet min/max, reconciliation tolerance), incident history, alert channel (Telegram/Slack/email). These are inputs only you can supply. (Sandbox/staging is no longer in this list — see "Staging environment" above.)

**Recommended next milestone** (matches the reviewer's suggestion): pick a subset of the six buildable-now endpoints above (health, transactions/summary, pending withdrawals/deposits, markets, orderbook-summary) and confirm whether the liabilities schema check can be unblocked, before writing any of the wallet-service integration work.
