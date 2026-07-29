# Changelog

All notable bitAgent changes are recorded here.

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
