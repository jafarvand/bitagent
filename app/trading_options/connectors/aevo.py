from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from ..models import OptionInstrument


@dataclass(frozen=True, slots=True)
class AevoConfig:
    env: str = "testnet"
    timeout_seconds: float = 10.0

    @property
    def rest_url(self) -> str:
        if self.env == "testnet":
            return "https://api-testnet.aevo.xyz"
        if self.env == "mainnet":
            return "https://api.aevo.xyz"
        raise ValueError("env must be 'testnet' or 'mainnet'")


class AevoPublicClient:
    """Small read-only Aevo REST adapter.

    M1 intentionally keeps this connector public/read-only. Authenticated order
    signing is added only after paper execution and risk controls are verified.
    """

    def __init__(self, config: AevoConfig | None = None, client: httpx.AsyncClient | None = None):
        self.config = config or AevoConfig()
        self._external_client = client is not None
        self._client = client or httpx.AsyncClient(
            base_url=self.config.rest_url,
            timeout=self.config.timeout_seconds,
        )

    async def aclose(self) -> None:
        if not self._external_client:
            await self._client.aclose()

    async def get_index(self, asset: str = "BTC") -> dict[str, Any]:
        response = await self._client.get("/index", params={"asset": asset.upper()})
        response.raise_for_status()
        return response.json()

    async def get_markets(self, asset: str = "BTC") -> list[dict[str, Any]]:
        response = await self._client.get("/markets", params={"asset": asset.upper()})
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in ("markets", "data", "result"):
                value = payload.get(key)
                if isinstance(value, list):
                    return value
        raise ValueError("Unexpected Aevo /markets response shape")

    async def get_orderbook(self, instrument_name: str) -> dict[str, Any]:
        response = await self._client.get(
            "/orderbook",
            params={"instrument_name": instrument_name},
        )
        response.raise_for_status()
        return response.json()

    async def list_options(self, asset: str = "BTC") -> list[OptionInstrument]:
        markets = await self.get_markets(asset)
        options: list[OptionInstrument] = []
        for market in markets:
            parsed = self._parse_option_market(market, asset)
            if parsed is not None:
                options.append(parsed)
        return options

    @staticmethod
    def _parse_option_market(market: dict[str, Any], asset: str) -> OptionInstrument | None:
        instrument_type = str(
            market.get("instrument_type")
            or market.get("type")
            or market.get("kind")
            or ""
        ).upper()
        name = str(
            market.get("instrument_name")
            or market.get("name")
            or market.get("symbol")
            or ""
        )
        option_type = str(
            market.get("option_type")
            or market.get("optionType")
            or ""
        ).upper()

        if not option_type and name:
            suffix = name.upper().split("-")[-1]
            if suffix in {"C", "CALL"}:
                option_type = "CALL"
            elif suffix in {"P", "PUT"}:
                option_type = "PUT"

        if instrument_type and "OPTION" not in instrument_type and option_type not in {"CALL", "PUT"}:
            return None
        if option_type in {"C", "CALL"}:
            option_type = "CALL"
        elif option_type in {"P", "PUT"}:
            option_type = "PUT"
        else:
            return None

        strike = _as_float(market.get("strike") or market.get("strike_price"))
        expiry = _as_int(
            market.get("expiry_ts")
            or market.get("expiry")
            or market.get("expiration")
            or market.get("expiry_timestamp")
        )
        if strike is None or expiry is None:
            return None

        return OptionInstrument(
            symbol=name or str(market.get("instrument_id") or ""),
            underlying=str(market.get("underlying") or asset).upper(),
            option_type=option_type,
            strike=strike,
            expiry_ts=expiry,
            bid=_as_float(market.get("bid") or market.get("best_bid")),
            ask=_as_float(market.get("ask") or market.get("best_ask")),
            mark=_as_float(market.get("mark") or market.get("mark_price")),
        )


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None
