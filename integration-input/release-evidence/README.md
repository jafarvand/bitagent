# 1.0 owner evidence input

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

The local files are ignored by Git. Do not include credentials, access tokens,
user identifiers, wallet addresses, transaction identifiers, or personal data.
The validator retains only status, replay results and SHA-256 evidence hashes in
the readiness response.
