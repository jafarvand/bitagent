import hashlib
import hmac
import time
import uuid
from urllib.parse import urlencode

import httpx

from app.config import settings


class ExchangeAPIError(RuntimeError):
    pass


class ExchangeClient:
    """Current pilot connector.

    Compatibility note: the exchange currently requires the shared token in a
    header as well as for HMAC. API contract v0.2 should replace that header
    with a non-secret key ID and sign the canonical query string.
    """

    def _headers(self, method: str, path: str) -> dict[str, str]:
        request_id = str(uuid.uuid4()).lower()
        timestamp = str(int(time.time()))
        canonical = "\n".join([method.upper(), path, timestamp, request_id])
        signature = hmac.new(
            settings.exchange_bot_token.encode(),
            canonical.encode(),
            hashlib.sha256,
        ).hexdigest()
        return {
            "X-Exchange-Bot-Authorization": f"Bearer {settings.exchange_bot_token}",
            "X-Request-Timestamp": timestamp,
            "X-Request-ID": request_id,
            "X-Request-Signature": signature,
            "Accept": "application/json",
        }

    async def get(self, path: str, params: dict | None = None) -> dict:
        if not settings.exchange_bot_token:
            raise ExchangeAPIError("Live mode requires EXCHANGE_BOT_TOKEN")
        url = f"{settings.exchange_api_base_url.rstrip('/')}{path}"
        try:
            async with httpx.AsyncClient(
                timeout=settings.exchange_timeout_seconds,
                follow_redirects=False,
            ) as client:
                response = await client.get(
                    url, params=params, headers=self._headers("GET", path)
                )
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ExchangeAPIError(str(exc)) from exc


exchange_client = ExchangeClient()
