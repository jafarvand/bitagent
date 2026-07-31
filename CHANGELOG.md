# Changelog

All notable bitAgent changes are recorded here.

## [1.1.22] - 2026-07-31

- Added deterministic prompt-injection detection, refusal, and audit receipts.

## [1.1.21] - 2026-07-31

- Added bounded chat-session exports with stable SHA-256 receipts.

## [1.1.20] - 2026-07-31

- Added a role-protected chat health endpoint without secret disclosure.

## [1.1.19] - 2026-07-31

- Expanded chat acceptance evaluation from six to ten operational and governance cases.

## [1.1.18] - 2026-07-31

- Added citation completeness gates for source time, record ID, and evidence hash.

## [1.1.17] - 2026-07-31

- Added fail-closed chat answer quality gates and per-check response metadata.

## [1.1.16] - 2026-07-31

- Added a configurable evidence-context budget with deterministic compaction.

## [1.1.15] - 2026-07-31

- Added configurable per-role/session chat rate limiting with retry guidance.

## [1.1.14] - 2026-07-31

- Added whitespace normalization and fail-fast control-character rejection.

## [1.1.13] - 2026-07-31

- Added fail-closed readiness answers using audit integrity and capability gaps.

## [1.1.12] - 2026-07-31

- Added deterministic capability-gap answers sourced from the feature registry.

## [1.1.11] - 2026-07-31

- Added bounded market-range risk answers with explicit volatility limitations.

## [1.1.10] - 2026-07-31

- Added deterministic executive brief and priority chat answers.

## [1.1.9] - 2026-07-31

- Added deterministic pending-withdrawal trend and direction answers.

## [1.1.8] - 2026-07-31

- Added stable chat question categories for routing and quality analytics.

## [1.1.7] - 2026-07-31

- Added auditor-only per-session receipts without question or answer content.

## [1.1.6] - 2026-07-31

- Added bounded, UUID-addressed, role-filtered conversation history.

## [1.1.5] - 2026-07-31

- Added client-supplied or generated UUID chat sessions persisted in chat audit records.

## [1.1.4] - 2026-07-31

- Added stable answer type and evidence-record metadata to every successful chat response.

## [1.1.3] - 2026-07-31

### Added

- Deterministic intent routing for pending counts, incident severity, market,
  source freshness, and root-cause evidence boundaries.
- Authoritative answers generated directly from the latest retained evidence.
- Six-question live acceptance accuracy improved from 16.67% to 100%.

## [1.1.2] - 2026-07-31

### Added

- Reproducible six-question read-only chat acceptance evaluation.
- Evidence-derived expected facts and deterministic term scoring.
- UTC timestamps, latency, answer, model, audit ID and accuracy logs.
- Failures and unavailable answers count as zero accuracy.

## [1.1.1] - 2026-07-31

### Added

- Authenticated Ollama `/api/tags` model discovery.
- Safe resolution from a generic `qwen` selector to one installed Qwen tag.
- Fail-closed errors for missing, unavailable, or ambiguous model names.
- End-to-end Basic Auth, discovery, and generation contract test.

## [1.1.0] - 2026-07-31

### Added

- First Ollama/Qwen read-only evidence chatbot.
- Operator/admin chat authorization and auditor/admin chat metadata audit.
- Deterministic prohibited-action refusal before model invocation.
- Evidence citations, freshness, confidence, limitations and non-execution statement.
- Prompt-injection boundary, credential redaction, bounded input and model timeout.
- Responsive frontend chat panel.

## [1.0.0] - 2026-07-30

### Changed

- Promoted the application to the read-only 1.0 pilot release.
- Retained fail-closed readiness reporting and prohibited-action boundaries.
- Updated the dashboard and public version metadata for the 1.0 release.
- Moved the application listener and published Docker port to 8999.
- Added top-level and dashboard live-refresh controls with visible request status.

## [0.10.0] - 2026-07-30

### Added

- Fail-closed 1.0 release-candidate decision manifest with explicit blockers.
- Stable SHA-256 receipt over candidate version and readiness-gate evidence.
- `GET /api/v0/releases/candidate` for controlled-pilot approval inspection.

## [0.9.3] - 2026-07-30

### Added

- Validated local input package for owner historical incidents, external
  security evidence, production identity evidence, and UAT approval.
- Owner incidents replay through the production deterministic rule.
- SHA-256 evidence receipts without exposing submitted evidence content.
- `python -m scripts.validate_release_inputs` handoff command.

## [0.9.2] - 2026-07-30

### Added

- Consistent SQLite operational-evidence backup with restored-chain verification.
- Reproducible `python -m scripts.backup_verify` operator check.
- Requirement-by-requirement 1.0 readiness evidence matrix.

## [0.9.1] - 2026-07-30

### Added

- Reproducible read-only upstream authentication probe.
- Live checks for missing authentication, expired timestamps, query tampering,
  and request-ID replay rejection.
- Credential-free probe evidence in the UAT readiness report.

## [0.9.0] - 2026-07-30

### Added

- Six sanitized golden-case replays for deterministic withdrawal severity.
- Local security self-tests for absolute refusal, non-execution and evidence-chain integrity.
- Machine-readable UAT report with explicit pass, fail and pending gates.
- `/api/v0/evaluations/replay` and `/api/v0/readiness` endpoints.

### Limitation

- Owner-supplied historical replay, upstream negative security tests, production
  identity and formal owner approval remain required for 1.0.

## [0.8.0] - 2026-07-30

### Added

- Role/capability policy with observe and enforced modes.
- Unconditional refusal catalogue for all prohibited exchange actions.
- Append-only hashed audit records for access decisions.

### Limitation

- `X-BitAgent-Role` is a pilot role signal, not production SSO/JWT identity proof.

## [0.7.0] - 2026-07-30

### Added

- Deterministic daily executive brief with priorities and evidence integrity.
- Local-only append-only operator feedback and aggregate feedback summary.
- Explicit guarantee that feedback cannot perform an exchange write.

## [0.6.0] - 2026-07-30

### Added

- Evidence-backed withdrawal slowdown investigation report.
- Direct conclusion, source timestamp, rule version, confidence and limitations.
- Approved master-runbook citation, triage guidance and missing-source list.

## [0.5.0] - 2026-07-30

### Added

- Historical aggregate deltas across a bounded evidence window.
- Decimal-safe market last-price change between retained observations.
- Configurable operations-evidence freshness alerts and limitations.

## [0.4.0] - 2026-07-30

### Added

- Local aggregate evidence persistence with no user-level records or secrets.
- Append-only SHA-256 hash chaining and full-chain integrity verification.
- Recent-evidence and audit-verification read APIs.

## [0.3.0] - 2026-07-30

### Added

- Decimal-safe market high-low range percentage and last-price position.
- Versioned warning/critical range thresholds and bounded market severity.
- Source freshness, confidence, limitations and no-action safety metadata.

## [0.2.0] - 2026-07-29

### Added

- Deterministic pending-withdrawal incident rule with versioned thresholds.
- Evidence references, freshness, incident timeline, confidence and limitations.
- Explicit investigation guidance and `action_executed: false` safety record.
- Compatibility with server-style `EXCHANGE_BOT_SERVICE_KEYS` credentials.

## [0.1.0] - 2026-07-29

### Changed

- Began the 0.1.0 API-contract v0.2 migration.
- Replaced the transmitted bearer secret with a public `X-Bot-Key-ID` header.
- Signed the normalized path, sorted query string, timestamp, request ID, and
  SHA-256 body hash.
- Added deterministic signing and credential-redaction tests.
- Added the Secure Connector dashboard identity and expanded capability map.

## [0.0.1] - 2026-07-29

### Added

- FastAPI read-only visibility backend
- Current exchange HMAC connector
- Safe mock mode with no credentials required
- Minimum operations and market dashboard
- API/feature coverage matrix
- Explicit partial and missing capability labels
- User-level read-only proxy endpoints, absent from the public UI
- Docker and local Python run configurations
- Health, dashboard, features and status APIs
- Initial automated contract tests
- Project plan, master runbook, architecture, API artifacts and task board

### Security boundary

- No write, trade, transfer, withdrawal, balance, user-state or configuration action
- No secret committed to the repository
- Live credentials loaded only from local environment configuration

### Known limitations

- Current upstream HMAC protocol transmits the shared secret and does not sign
  query parameters; API contract v0.2 must correct this before production use.
- No treasury, liabilities, reconciliation, queue, worker, health or order-book
  endpoint exists yet.
- Slowdown visibility is limited to pending count and cannot establish root cause.
