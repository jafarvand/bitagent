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

    def __init__(self):
        self._consecutive_failures = 0
        self._circuit_open_until = 0.0
        self._metrics = {
            "requests": 0, "successes": 0, "failures": 0, "retries": 0,
            "last_success_at": None, "last_failure_at": None, "last_error_type": None,
        }

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
        key_id, secret = settings.exchange_credentials()
        signature = hmac.new(
            secret.encode(),
            canonical.encode(),
            hashlib.sha256,
        ).hexdigest()
        return {
            "X-Bot-Key-ID": key_id,
            "X-Request-Timestamp": timestamp,
            "X-Request-ID": request_id,
            "X-Request-Signature": signature,
            "Accept": "application/json",
        }

    async def get(self, path: str, params: dict | None = None) -> dict:
        key_id, secret = settings.exchange_credentials()
        if not key_id or not secret:
            raise ExchangeAPIError(
                "Live mode requires EXCHANGE_BOT_KEY_ID and EXCHANGE_BOT_SECRET "
                "or EXCHANGE_BOT_SERVICE_KEYS"
            )
        normalized_path = self._normalized_path(path)
        query_string = self._query_string(params)
        url = f"{settings.exchange_api_base_url.rstrip('/')}{normalized_path}"
        if query_string:
            url = f"{url}?{query_string}"
        if time.monotonic() < self._circuit_open_until:
            raise ExchangeAPIError("Exchange circuit breaker is open")
        self._metrics["requests"] += 1
        last_error = None
        last_retryable = True
        for attempt in range(settings.exchange_max_retries + 1):
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
                result = response.json()
                self._consecutive_failures = 0
                self._circuit_open_until = 0.0
                self._metrics["successes"] += 1
                self._metrics["last_success_at"] = str(int(time.time()))
                return result
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
                retryable = status is None or status == 429 or status >= 500
                last_retryable = retryable
                if not retryable or attempt >= settings.exchange_max_retries:
                    break
                self._metrics["retries"] += 1
                retry_after = (
                    float(exc.response.headers.get("Retry-After", 0))
                    if isinstance(exc, httpx.HTTPStatusError) else 0
                )
                delay = max(retry_after, settings.exchange_retry_base_seconds * (2 ** attempt))
                await asyncio.sleep(min(delay, 5.0))
        if last_retryable:
            self._consecutive_failures += 1
        else:
            self._consecutive_failures = 0
        self._metrics["failures"] += 1
        self._metrics["last_failure_at"] = str(int(time.time()))
        self._metrics["last_error_type"] = type(last_error).__name__
        if last_retryable and self._consecutive_failures >= settings.exchange_circuit_failure_threshold:
            self._circuit_open_until = time.monotonic() + settings.exchange_circuit_recovery_seconds
        message = str(last_error)
        if isinstance(last_error, httpx.HTTPStatusError):
            body = last_error.response.json() if last_error.response.content else {}
            error = body.get("error", body) if isinstance(body, dict) else {}
            code = error.get("code") if isinstance(error, dict) else None
            detail = error.get("message") if isinstance(error, dict) else None
            message = f"HTTP {last_error.response.status_code}: {code or detail or 'exchange request failed'}"
        raise ExchangeAPIError(message) from last_error

    def health_snapshot(self) -> dict:
        circuit_open = time.monotonic() < self._circuit_open_until
        return {
            **self._metrics, "circuit": "open" if circuit_open else "closed",
            "consecutive_failures": self._consecutive_failures,
            "timeout_seconds": settings.exchange_timeout_seconds,
            "max_retries": settings.exchange_max_retries,
            "read_only_methods": ["GET"], "credentials_exposed": False,
        }


exchange_client = ExchangeClient()
import asyncio
