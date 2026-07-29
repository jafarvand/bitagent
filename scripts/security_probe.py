"""Run non-mutating authentication checks against the configured exchange API."""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

from app.config import settings
from app.exchange import ExchangeClient


REPORT_PATH = Path(".data/upstream-security-report.json")
SAFE_PATH = "/api/bot/operations"


async def run() -> dict:
    client = ExchangeClient()
    base_url = settings.exchange_api_base_url.rstrip("/")
    query = "date_from=2026-07-01&date_to=2026-07-02"
    url = f"{base_url}{SAFE_PATH}?{query}"
    checks = []

    async with httpx.AsyncClient(
        timeout=settings.exchange_timeout_seconds,
        follow_redirects=False,
    ) as http:
        missing = await http.get(url)
        checks.append({
            "id": "missing-authentication",
            "expected_status": 401,
            "actual_status": missing.status_code,
            "passed": missing.status_code == 401,
        })

        expired_headers = client._headers(
            "GET", SAFE_PATH, query, timestamp="1"
        )
        expired = await http.get(url, headers=expired_headers)
        checks.append({
            "id": "expired-timestamp",
            "expected_status": 401,
            "actual_status": expired.status_code,
            "passed": expired.status_code == 401,
        })

        signed_query = "date_from=2026-07-01&date_to=2026-07-02"
        changed_query = "date_from=2026-07-01&date_to=2026-07-03"
        tampered_headers = client._headers("GET", SAFE_PATH, signed_query)
        tampered = await http.get(
            f"{base_url}{SAFE_PATH}?{changed_query}", headers=tampered_headers
        )
        checks.append({
            "id": "query-tampering",
            "expected_status": 401,
            "actual_status": tampered.status_code,
            "passed": tampered.status_code == 401,
        })

        replay_headers = client._headers("GET", SAFE_PATH, query)
        first = await http.get(url, headers=replay_headers)
        replay = await http.get(url, headers=replay_headers)
        checks.append({
            "id": "request-id-replay",
            "expected_status": 409,
            "actual_status": replay.status_code,
            "prerequisite_status": first.status_code,
            "passed": first.status_code == 200 and replay.status_code == 409,
        })

    report = {
        "schema_version": "1.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "target": "configured_exchange_api",
        "method": "GET",
        "path": SAFE_PATH,
        "read_only": True,
        "checks": checks,
        "passed": sum(check["passed"] for check in checks),
        "total": len(checks),
        "all_passed": all(check["passed"] for check in checks),
        "contains_credentials": False,
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    result = asyncio.run(run())
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["all_passed"] else 1)
