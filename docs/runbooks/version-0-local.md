# Version 0 Local Runbook

## Start in safe mock mode

```bash
cp .env.example .env
docker compose up --build
```

Open `http://localhost:8000` and confirm the header shows `MOCK MODE`.

## Start with a live read-only API

1. Create a dedicated read-only exchange identity.
2. Restrict it to the eight documented `GET` routes.
3. Configure its egress IP allowlist and revocation procedure.
4. Store its token only in local `.env` or a deployment secret manager.
5. Set `BITAGENT_MODE=live`.
6. Restart the container and open the dashboard.

Do not paste the token into chat, source code, Git, screenshots or issue bodies.

## Smoke checks

```bash
curl http://localhost:8000/health
curl http://localhost:8000/api/v0/status
curl "http://localhost:8000/api/v0/dashboard?market=BTC_USDT&days=30"
```

Confirm:

- `read_only` is true;
- the intended mode is reported;
- request timestamps are fresh;
- operations and market values match direct API checks;
- no secret appears in output or logs.

## Stop

```bash
docker compose down
```

## Incident: upstream connection failure

1. Keep bitAgent read-only; do not broaden permissions.
2. Check `/health` and `/api/v0/status`.
3. Verify clock synchronization because signatures expire after 60 seconds.
4. Verify base URL, TLS, DNS, IP allowlist and token rotation state.
5. Compare one signed request using the private Postman environment.
6. Revoke the token immediately if exposure is suspected.
