# bitAgent

Read-only Exchange Operations & Risk Copilot.

Current release: **2.0.0 — XIMA Evidence Platform**

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

Open <http://localhost:8999>.

For the production host, where the external `nginx-proxy` network and ACME
challenge directory already exist, apply the production override explicitly:

```bash
docker compose -f docker-compose.yml -f docker-compose.production.yml up --build -d
```

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

## Ollama chat provider

The first read-only chat agent uses the configured HTTPS Ollama endpoint. It
remains disabled until a non-exposed password is installed locally:

```env
BITAGENT_CHAT_ENABLED=false
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=https://ollama.zekabot.com
OLLAMA_MODEL=qwen
OLLAMA_USERNAME=replace-locally
OLLAMA_PASSWORD=replace-locally-after-rotation
```

Use the exact model name returned by `GET /api/tags` after authentication. Never
commit the Basic Auth password or place it in a URL.

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
- `GET /api/v0/releases/candidate` (1.0 gate decision and evidence receipt)
- `POST /api/v0/chat` (operator/admin; retained evidence only)
- `GET /api/v0/chat/models` (authenticated Ollama model discovery)
- `GET /api/v0/chat/sessions/{session_id}` (bounded operator session history)
- `GET /api/v0/chat/sessions/{session_id}/export` (bounded export with SHA-256 receipt)
- `GET /api/v0/chat/health` (safe evidence, audit, and Ollama readiness state)
- `GET /api/v0/audit/chat/recent` (auditor/admin; metadata only)
- `GET /api/v0/audit/chat/sessions/{session_id}` (content-free session receipts)
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

## Chat evaluation

Run the evidence-derived acceptance set against the local service:

```bash
python -m scripts.evaluate_chat --base-url http://127.0.0.1:8999
```

The harness records UTC question time, latency, answer, expected and matched
facts, accuracy, model and audit ID under `.data/evaluations/`. Unavailable
answers score zero and are never omitted from the overall result.

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
| 0.9.0 | Replay, security and UAT readiness tooling | Complete |
| 0.9.1 | Reproducible upstream negative-auth security probe | Complete |
| 0.9.2 | Backup/restore verification and 1.0 evidence matrix | Complete |
| 0.9.3 | Validated owner incident, security, identity and UAT inputs | Complete |
| 0.10.0 | Fail-closed 1.0 candidate decision and evidence receipt | Complete |
| 1.0.0 | Read-only pilot release; evidence gates remain fail-closed | Complete |
| 1.1.0 | Ollama/Qwen read-only evidence chatbot with citations and audit | Complete |
| 1.1.1 | Authenticated model discovery and exact Qwen tag resolution | Complete |
| 1.1.2 | Timestamped chatbot question, latency and accuracy evaluation | Complete |
| 1.1.3 | Deterministic authoritative answers; acceptance accuracy 100% | Complete |
| 1.1.4 | Structured deterministic, refusal, and LLM response contract | Complete |
| 1.1.5 | UUID chat sessions persisted with every audit record | Complete |
| 1.1.6 | Bounded role-filtered chat session history | Complete |
| 1.1.7 | Auditor-only content-free session audit receipts | Complete |
| 1.1.8 | Stable operations, market, quality, safety, and open-ended categories | Complete |
| 1.1.9 | Deterministic pending-withdrawal trend answers | Complete |
| 1.1.10 | Deterministic executive brief and priority answers | Complete |
| 1.1.11 | Bounded deterministic market-range risk answers | Complete |
| 1.1.12 | Deterministic capability-gap answers from the feature registry | Complete |
| 1.1.13 | Fail-closed readiness boundary answers | Complete |
| 1.1.14 | Normalized questions and control-character rejection | Complete |
| 1.1.15 | Per-role/session in-memory chat rate limiting | Complete |
| 1.1.16 | Bounded and compacted Ollama evidence context | Complete |
| 1.1.17 | Non-empty, bounded, cited, redacted, non-executing answer gates | Complete |
| 1.1.18 | Required citation timestamps, record IDs, and evidence hashes | Complete |
| 1.1.19 | Ten-case operational, safety, capability, and governance evaluation | Complete |
| 1.1.20 | Safe chat dependency and evidence health reporting | Complete |
| 1.1.21 | Bounded role-filtered session export with SHA-256 receipt | Complete |
| 1.1.22 | Deterministic prompt-injection detection, refusal, and audit | Complete |
| 1.9.0 | Marketing data boundaries, lifecycle taxonomy, planning schema, and audit | Complete |
| 1.9.1 | Evidence-backed acquisition funnels, briefs, and KPI targets | Complete |
| 1.9.2 | Lifecycle retention, adoption, onboarding, and re-engagement plans | Complete |
| 1.9.3 | Multi-channel variants, compliance checks, and campaign calendar | Complete |
| 1.9.4 | Funnel reporting, attribution boundaries, experiments, and briefs | Complete |
| 1.9.5 | Exact approvals, test audiences, dry runs, rollback, and pause | Complete |
| 1.10.0 | Limited controlled scheduling, cancellation, and monitoring | Complete |
| 2.0.0 | Multi-domain evidence contracts, lineage, freshness, quality, and replay | Current |
| 2.1.0 | Operations dependency, error, queue, capacity, and incident intelligence | Planned |
| 2.2.0 | Liquidity, volatility, exposure, concentration, and market quality | Planned |
| 2.3.0 | Treasury, liabilities, wallet thresholds, reconciliation, and obligations | Planned |
| 2.4.0 | Transparent AML/fraud prioritization and evidence packs | Planned |
| 2.5.0 | Correlated security intelligence and escalation | Planned |
| 2.6.0 | Support intelligence and governed cited knowledge | Planned |
| 2.7.0 | Cross-domain policy, registry, adversarial and quality evaluation | Planned |
| 2.8.0 | Shadow outcomes, reliability evidence, and readiness gates | Planned |
| 2.9.0 | General maker-checker action sandbox and rollback | Planned |

## Project documents

- [MVP plan and task board](docs/planning/mvp-v0.md)
- [Approved 16-week project plan](docs/planning/project-plan.md)
- [Marketing Growth Agent plan and infographic](docs/planning/marketing-growth-agent.md)
- [Remaining XIMA version roadmap](docs/planning/xima-version-roadmap.md)
- [Master operations runbook](docs/runbooks/master-runbook.md)
- [Architecture](docs/architecture/version-0.md)
- [API contract and Postman collection](docs/api/)
- [Security decision: read-only first](docs/decisions/0001-read-only-first.md)
- [Changelog](CHANGELOG.md)
- [1.0 readiness evidence](docs/releases/1.0-readiness.md)
- [1.0 owner evidence inputs](integration-input/release-evidence/README.md)
