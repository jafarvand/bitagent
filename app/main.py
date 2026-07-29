from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import mock_data
from app.config import settings
from app.exchange import ExchangeAPIError, exchange_client
from app.features import FEATURES

VERSION = "0.1.0"
ROOT = Path(__file__).parent

app = FastAPI(
    title="bitAgent",
    version=VERSION,
    description="Read-only secure exchange connector and visibility dashboard.",
)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/health")
async def health():
    return {"status": "ok", "version": VERSION, "mode": settings.bitagent_mode}


@app.get("/api/v0/status")
async def status():
    return {
        "name": "bitAgent",
        "version": VERSION,
        "release": "Secure Connector",
        "mode": settings.bitagent_mode,
        "read_only": True,
        "base_url_configured": bool(settings.exchange_api_base_url),
        "key_id_configured": bool(settings.exchange_bot_key_id),
        "secret_configured": bool(settings.exchange_bot_secret),
        "timestamp": datetime.now(UTC).isoformat(),
    }


@app.get("/api/v0/features")
async def features():
    counts = {
        state: sum(feature["status"] == state for feature in FEATURES)
        for state in ("available", "partial", "missing")
    }
    return {"version": VERSION, "counts": counts, "items": FEATURES}


async def fetch_dashboard(market: str, days: int) -> tuple[dict, dict]:
    if settings.bitagent_mode == "mock":
        return mock_data.operations(days), mock_data.market(market)
    now = datetime.now(UTC)
    params = {
        "date_from": (now - timedelta(days=days)).date().isoformat(),
        "date_to": now.date().isoformat(),
    }
    operations = await exchange_client.get("/api/bot/operations", params)
    market_data = await exchange_client.get(
        f"/api/bot/market/{market}/summary"
    )
    return operations, market_data


@app.get("/api/v0/dashboard")
async def dashboard(
    market: str = Query(default=settings.bitagent_default_market, pattern=r"^[A-Z0-9]+_[A-Z0-9]+$"),
    days: int = Query(default=30, ge=1, le=366),
):
    try:
        operations, market_data = await fetch_dashboard(market, days)
    except ExchangeAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    pending = int(operations.get("data", {}).get("pending_withdrawals", 0))
    return {
        "version": VERSION,
        "mode": settings.bitagent_mode,
        "operations": operations,
        "market": market_data,
        "signals": [
            {
                "severity": "warning" if pending else "healthy",
                "title": "Pending withdrawals",
                "value": pending,
                "explanation": (
                    "Pending withdrawals need investigation. Version 0 cannot "
                    "yet determine age, queue backlog, worker state or root cause."
                    if pending
                    else "No pending withdrawals reported for this period."
                ),
            }
        ],
    }


UserResource = Literal[
    "summary", "balances", "trades", "deposits", "withdrawals", "pnl"
]


@app.get("/api/v0/users/{user_id}/{resource}")
async def user_resource(
    user_id: int,
    resource: UserResource,
    date_from: str | None = None,
    date_to: str | None = None,
):
    if settings.bitagent_mode == "mock":
        return {
            "mode": "mock",
            "data": {"user_id": user_id, "resource": resource, "items": []},
            "meta": {
                "generated_at": datetime.now(UTC).isoformat(),
                "notice": "No user-level fixture is included to avoid sample PII.",
            },
        }
    params = {
        key: value
        for key, value in {"date_from": date_from, "date_to": date_to}.items()
        if value
    }
    try:
        return await exchange_client.get(
            f"/api/bot/user/{user_id}/{resource}", params or None
        )
    except ExchangeAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
