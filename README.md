# bitAgent

Read-only Exchange Operations & Risk Copilot.

Current release: **0.9.0 — Pilot Gate**

## What version 0 shows

- Exchange API connection state and response freshness
- 30-day operations totals
- Pending-withdrawal warning
- Single-market snapshot
- Feature/API coverage matrix
- Explicit gaps: treasury, liabilities, queues, workers, reconciliation, order-book risk
- Mock mode for safe local evaluation
- Live mode using the exchange's current HMAC protocol

No trade, transfer, withdrawal, balance, user, or configuration write action exists.

## Run

Python 3.11+ and Docker are supported.

```bash
cp .env.example .env
docker compose up --build
```

Open <http://localhost:8000>.

Without credentials the app starts in `mock` mode. For live read-only data, edit
`.env`:

```env
BITAGENT_MODE=live
EXCHANGE_API_BASE_URL=https://devapi.zekabot.com
EXCHANGE_BOT_KEY_ID=bitagent-pilot-01
EXCHANGE_BOT_SECRET=replace-locally
```

Never commit `.env` or a real signing secret. The key ID is public; the secret
must remain only in an approved local secret store.

## Local Python run

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## API

- `GET /api/v0/status`
- `GET /api/v0/features`
- `GET /api/v0/dashboard?market=BTC_USDT&days=30`
- `GET /api/v0/evidence/recent?limit=20`
- `GET /api/v0/audit/verify`
- `GET /api/v0/trends?limit=30`
- `GET /api/v0/investigations/withdrawal-slowdown`
- `GET /api/v0/briefs/daily`
- `POST /api/v0/feedback` (local-only; never writes to the exchange)
- `GET /api/v0/feedback/summary`
- `POST /api/v0/policy/evaluate`
- `GET /api/v0/audit/access/recent`
- `GET /api/v0/evaluations/replay`
- `GET /api/v0/readiness`
- `GET /api/v0/users/{user_id}/{resource}` where resource is one of
  `summary`, `balances`, `trades`, `deposits`, `withdrawals`, `pnl`
- `GET /health`

The user-resource proxy is disabled in the UI by default because it can expose
user-level financial data. It remains read-only and requires a deliberate API
call.

## Tests

```bash
pytest
```

## Version plan

| Version | Focus | Status |
|---|---|---|
| 0.0.1 | API connector, mock/live mode, minimum dashboard, coverage matrix | Complete |
| 0.1.0 | Secure key-ID signing, replay resistance, complete schemas, readiness UI | Complete |
| 0.2.0 | Deterministic withdrawal signal, evidence contract and incident timeline | Complete |
| 0.3.0 | Decimal-safe market range analytics and bounded risk evidence | Complete |
| 0.4.0 | Aggregate evidence ledger and tamper-evident audit verification | Complete |
| 0.5.0 | Historical trends, comparisons and freshness alerts | Complete |
| 0.6.0 | Investigation reports and cited runbook guidance | Complete |
| 0.7.0 | Executive brief and local operator feedback | Complete |
| 0.8.0 | Pilot RBAC, refusal policy and expanded access audit | Complete |
| 0.9.0 | Replay, security and UAT readiness tooling | Current |
| 1.0.0 | Approved read-only pilot after replay, security and UAT gates | Planned |

## Project documents

- [MVP plan and task board](docs/planning/mvp-v0.md)
- [Approved 16-week project plan](docs/planning/project-plan.md)
- [Master operations runbook](docs/runbooks/master-runbook.md)
- [Architecture](docs/architecture/version-0.md)
- [API contract and Postman collection](docs/api/)
- [Security decision: read-only first](docs/decisions/0001-read-only-first.md)
- [Changelog](CHANGELOG.md)
