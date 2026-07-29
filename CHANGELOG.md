# Changelog

All notable bitAgent changes are recorded here.

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
