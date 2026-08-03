# 3.0 read-only pilot evidence input

Copy each `*.example.json` file to the matching `*.local.json` filename, replace
the placeholders with truthful owner-approved evidence, and run:

```powershell
python -m scripts.validate_release_inputs
```

Required local filenames:

- `incidents.local.json` — 5–20 sanitized, owner-approved historical incidents.
- `security.local.json` — security-owner IP, scope, rotation and revocation results.
- `identity.local.json` — identity-owner SSO/JWT, MFA and access-review evidence.
- `uat-approval.local.json` — operations and risk-owner approval.
- `pilot.local.json` — consolidated exchange-route, upstream-source, shadow,
  reliability, training, eight-domain acceptance, and steering evidence for the
  `3.0.0-rc.1` pilot manifest. Start from `pilot.example.json`.

The local files are ignored by Git. Do not include credentials, access tokens,
user identifiers, wallet addresses, transaction identifiers, or personal data.
The validator retains only status, replay results and SHA-256 evidence hashes in
the readiness response.

The example values deliberately fail closed. Do not change any boolean to
`true`, list a source as live, or add an approval name unless the corresponding
signed test report or owner record exists. Controlled actions remain disabled
regardless of this package.
