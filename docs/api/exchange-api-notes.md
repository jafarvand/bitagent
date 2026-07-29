# bitAgent read-only pilot — exchange-backend

Companion to `openapi.yaml` and `bitAgent.postman_collection.json` in this folder.

## Backend technology

- **exchange-backend**: PHP 7.2, Phalcon 3.3.1 (MVC), running under Apache 2.4/mod_php in Docker. Routes defined in `config/exchange-backend/html/config/routes.php`; the bot-facing controller is `data/exchange-backend/apps/Rest/Controller/BotController.php`.
- **Matching engine**: C (`exchange-core`), reached from PHP only via an internal JSON-RPC client (`Core\Plugin\JsonRPC`) — no direct DB access to it from this controller.
- **MySQL**: `exchange-backend-mysql` backs `User`, `Deposit`, `Withdraw`, `UserOrder`, `IncomeDetail` models used here.
- **Deployment**: single-host Docker Compose (no k8s). `exchange-backend`'s `apps/` and `config/` are bind-mounted from the host, so PHP edits take effect immediately — no image rebuild needed; only a container recreate (`docker compose up -d exchange-backend`) is needed when env vars change.

## Authentication method

Custom HMAC-SHA256 service-to-service signing — **not** JWT, not a plain API key. Implemented in `Core\Security\BotServiceAuth`, enforced in `BotController::beforeExecuteRoute`.

**Signing recipe:**
1. Canonical string: `METHOD\nPATH\nTIMESTAMP\nREQUEST_ID` (method uppercased, request ID lowercased, joined with `\n`).
2. `signature = hex(HMAC-SHA256(canonical, shared_secret))`.
3. Send four headers on every request:
   - `X-Exchange-Bot-Authorization: Bearer <shared_secret>` — **use this header, not `Authorization`**. This Apache/mod_php build does not forward the standard `Authorization` header into PHP; `Core\Security\BotServiceAuth` checks `Authorization` first and falls back to `X-Exchange-Bot-Authorization`, and only the fallback was confirmed working end-to-end.
   - `X-Request-Timestamp: <unix seconds>` — must be within 60s of server time.
   - `X-Request-ID: <uuid>` — must be a valid v1-5 UUID; echoed back in the response for audit correlation.
   - `X-Request-Signature: <hex hmac>`.
4. Secret lives in `.env.bitagent` at the repo root (`EXCHANGE_BOT_SERVICE_TOKENS`, comma-separated for rotation — old + new token both valid during a rotation window), loaded into the `exchange-backend` container via `env_file` in `docker-compose.yml`. **Not committed to the config file itself, not printed in this doc.**
5. Optional IP allowlist via `EXCHANGE_BOT_ALLOWED_IPS` (comma-separated) — currently **unset** (open) per the 2026-07-29 pilot decision; add the bitAgent's egress IP there once known.
6. All failures return a structured JSON error (`{"error":{"code","message","request_id"}}`) with the appropriate status: 503 if the service token isn't configured, 403 for a denied IP, 401 for a bad/missing signature.

There is no write, trade, transfer, or withdrawal action reachable through this controller — an earlier `cancelOrderAction` was removed before routing anything live.

## Available read-only endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/bot/operations` | Aggregated deposit/withdrawal/order counts + fee revenue for a date range |
| GET | `/api/bot/market/{marketIdentifier}/summary` | Single market ticker/status (e.g. `BTC_USDT`) |
| GET | `/api/bot/user/{userId}/summary` | Account status, KYC level, order counts |
| GET | `/api/bot/user/{userId}/balances` | Per-asset available/blocked/total + IRT valuation |
| GET | `/api/bot/user/{userId}/trades` | Executed trades in a date range |
| GET | `/api/bot/user/{userId}/deposits` | Deposit records in a date range (tx hash/destination masked) |
| GET | `/api/bot/user/{userId}/withdrawals` | Withdrawal records in a date range (tx hash/destination masked) |
| GET | `/api/bot/user/{userId}/pnl` | Execution PnL in a date range (partial — cost-basis ledger not connected yet) |

**Known gap:** none of these give aggregated **treasury** (exchange hot-wallet balances) or **liabilities** (aggregate customer balance per asset across all users) data — see "Not yet built" below.

## Sanitized sample responses

Captured live against `exchange-backend` on 2026-07-29, IDs/amounts are real production values as of that moment (this is a live exchange, not synthetic data — treat these numbers as a shape reference, not a fixture to hardcode against).

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

## Not yet built (flagged in the original requirements, still open)

- **Treasury** (exchange hot-wallet balances/status) and **Liabilities** (aggregated customer balance per asset) have no endpoint yet. The closest existing thing is `market-monitor`'s internal `user_totals` job (Python sidecar, `/status/user_totals`, reachable only from `exchange-admin`'s network, not from bitAgent) — it computes per-user totals from `exchange-core-mysql`'s `trade_log.slice_balance_<unix_ts>` snapshot tables, which is the right data source, but nothing aggregates or exposes it outside that sidecar today. Building this safely means confirming the live schema first (a `SHOW TABLES`/`DESCRIBE` was blocked by policy during this session as a live-prod DB action) rather than guessing at column names.
- **Wallet-mon queue backlog / Kafka consumer lag**: no endpoint on any `*-wallet-mon` service or on `core-webhook-handler` exposes this.
- **Confirmation count** and **failure/rejection reason** on withdrawals/deposits: not present in the `Withdraw`/`Deposit` models as queried here — would need either a schema check or a different data source.
- **Sandbox/staging environment, business thresholds, incident history, alert channel (Telegram/Slack/email)**: none exist yet; these are inputs only you can supply, not things derivable from this codebase.
