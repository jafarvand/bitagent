import hashlib
import hmac
import posixpath
import time
import uuid
from collections.abc import Mapping, Sequence
from urllib.parse import quote, urlencode, urlsplit

import httpx

from app.config import settings


class ExchangeAPIError(RuntimeError):
    pass


class ExchangeClient:
    """Read-only API-contract v0.2 connector."""

    @staticmethod
    def _normalized_path(path: str) -> str:
        parsed = urlsplit(path)
        if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
            raise ExchangeAPIError("Exchange path must be an absolute path without a query")
        if not parsed.path.startswith("/"):
            raise ExchangeAPIError("Exchange path must start with '/'")
        normalized = "/" + posixpath.normpath(
            "/" + parsed.path.lstrip("/")
        ).lstrip("/")
        if parsed.path.endswith("/") and normalized != "/":
            normalized += "/"
        return normalized

    @staticmethod
    def _query_string(params: Mapping | None) -> str:
        if not params:
            return ""
        pairs: list[tuple[str, str]] = []
        for key, value in params.items():
            values = (
                value
                if isinstance(value, Sequence)
                and not isinstance(value, (str, bytes, bytearray))
                else [value]
            )
            pairs.extend((str(key), str(item)) for item in values if item is not None)
        pairs.sort(key=lambda pair: pair[0])
        return urlencode(pairs, quote_via=quote)

    def _headers(
        self,
        method: str,
        path: str,
        query_string: str = "",
        body: bytes = b"",
        *,
        timestamp: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, str]:
        request_id = (request_id or str(uuid.uuid4())).lower()
        timestamp = timestamp or str(int(time.time()))
        body_hash = hashlib.sha256(body).hexdigest()
        canonical = "\n".join(
            [
                method.upper(),
                self._normalized_path(path),
                query_string,
                timestamp,
                request_id,
                body_hash,
            ]
        )
        signature = hmac.new(
            settings.exchange_bot_secret.encode(),
            canonical.encode(),
            hashlib.sha256,
        ).hexdigest()
        return {
            "X-Bot-Key-ID": settings.exchange_bot_key_id,
            "X-Request-Timestamp": timestamp,
            "X-Request-ID": request_id,
            "X-Request-Signature": signature,
            "Accept": "application/json",
        }

    async def get(self, path: str, params: dict | None = None) -> dict:
        if not settings.exchange_bot_key_id or not settings.exchange_bot_secret:
            raise ExchangeAPIError(
                "Live mode requires EXCHANGE_BOT_KEY_ID and EXCHANGE_BOT_SECRET"
            )
        normalized_path = self._normalized_path(path)
        query_string = self._query_string(params)
        url = f"{settings.exchange_api_base_url.rstrip('/')}{normalized_path}"
        if query_string:
            url = f"{url}?{query_string}"
        try:
            async with httpx.AsyncClient(
                timeout=settings.exchange_timeout_seconds,
                follow_redirects=False,
            ) as client:
                response = await client.get(
                    url,
                    headers=self._headers("GET", normalized_path, query_string),
                )
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ExchangeAPIError(str(exc)) from exc


exchange_client = ExchangeClient()
