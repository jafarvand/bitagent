# ADR-0002: API authentication v0.2

Status: Proposed  
Date: 2026-07-29

## Context

The pilot protocol transmits the shared HMAC secret in
`X-Exchange-Bot-Authorization` and excludes query parameters from the signature.
Version 0 supports this only for compatibility.

## Proposed decision

Use a public identifier plus a secret that never crosses the network:

```text
X-Bot-Key-ID: bitagent-pilot-01
X-Request-Timestamp: unix-seconds
X-Request-ID: UUID
X-Request-Signature: HMAC-SHA256(secret, canonical-request)
```

Canonical request:

```text
METHOD
NORMALIZED_PATH
SORTED_QUERY_STRING
TIMESTAMP
REQUEST_ID
BODY_SHA256
```

Client canonicalization rules:

- Paths are absolute, contain no embedded query or fragment, and resolve `.`
  and `..` segments before signing.
- Query keys and values are converted to strings, stably sorted by key in byte
  order, and percent-encoded with spaces as `%20`; repeated keys are retained.
- GET requests use the SHA-256 digest of an empty byte string as `BODY_SHA256`.
- The exact encoded query string included in the signature is sent upstream.

The server rejects expired timestamps and previously used request IDs, applies
per-key scopes and rate limits, and supports immediate revocation and rotation.

## Acceptance

- Secret is never transmitted or logged.
- Query mutation invalidates the signature.
- Replay test returns `409`.
- Expired request returns `401`.
- Denied scope/IP returns `403`.
- Rotation is verified without downtime.
