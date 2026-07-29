# Changelog

All notable bitAgent changes are recorded here.

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
