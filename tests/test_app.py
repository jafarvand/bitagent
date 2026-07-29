import hashlib
import hmac

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.exchange import ExchangeClient
from app.main import app


client = TestClient(app)


@pytest.fixture(autouse=True)
def mock_mode(monkeypatch):
    monkeypatch.setattr(settings, "bitagent_mode", "mock")


def test_health_is_read_only_version_zero_line():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["version"] == "0.2.0"


def test_dashboard_mock_contract():
    response = client.get("/api/v0/dashboard?market=BTC_USDT&days=30")
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "mock"
    assert body["operations"]["data"]["pending_withdrawals"] == 42
    assert body["market"]["data"]["market"] == "BTC_USDT"
    incident = body["incident"]
    assert incident["severity"] == "warning"
    assert incident["observed"]["pending_count"] == 42
    assert incident["rule"] == {
        "id": "withdrawal-pending-count",
        "version": "1.0.0",
    }
    assert incident["action_executed"] is False
    assert incident["confidence"] == "limited"


def test_feature_gaps_are_explicit():
    response = client.get("/api/v0/features")
    assert response.status_code == 200
    body = response.json()
    assert body["counts"]["available"] >= 6
    assert body["counts"]["missing"] >= 1
    assert any(item["id"] == "auth-v02" for item in body["items"])


def test_invalid_market_is_rejected():
    response = client.get("/api/v0/dashboard?market=bad-market")
    assert response.status_code == 422


def test_v02_signature_covers_sorted_query_and_empty_body_hash(monkeypatch):
    monkeypatch.setattr(settings, "exchange_bot_key_id", "pilot-key")
    monkeypatch.setattr(settings, "exchange_bot_secret", "test-secret")
    exchange = ExchangeClient()
    query = exchange._query_string(
        {"z": "last value", "asset": ["USDT", "BTC"]}
    )

    headers = exchange._headers(
        "get",
        "/api/bot/transactions/../operations",
        query,
        timestamp="1785350000",
        request_id="AAAAAAAA-BBBB-4CCC-8DDD-EEEEEEEEEEEE",
    )

    assert query == "asset=USDT&asset=BTC&z=last%20value"
    canonical = "\n".join(
        [
            "GET",
            "/api/bot/operations",
            query,
            "1785350000",
            "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
            hashlib.sha256(b"").hexdigest(),
        ]
    )
    expected = hmac.new(
        b"test-secret", canonical.encode(), hashlib.sha256
    ).hexdigest()
    assert headers["X-Bot-Key-ID"] == "pilot-key"
    assert "X-Exchange-Bot-Authorization" not in headers
    assert headers["X-Request-Signature"] == expected


def test_status_reports_v02_credentials_without_exposing_values(monkeypatch):
    monkeypatch.setattr(settings, "exchange_bot_key_id", "pilot-key")
    monkeypatch.setattr(settings, "exchange_bot_secret", "test-secret")

    body = client.get("/api/v0/status").json()

    assert body["key_id_configured"] is True
    assert body["secret_configured"] is True
    assert "pilot-key" not in str(body)
    assert "test-secret" not in str(body)


def test_combined_service_keys_are_supported(monkeypatch):
    monkeypatch.setattr(settings, "exchange_bot_key_id", "")
    monkeypatch.setattr(settings, "exchange_bot_secret", "")
    monkeypatch.setattr(
        settings,
        "exchange_bot_service_keys",
        "pilot-key:test-secret,rotation-key:rotation-secret",
    )

    assert settings.exchange_credentials() == ("pilot-key", "test-secret")
    body = client.get("/api/v0/status").json()
    assert body["key_id_configured"] is True
    assert body["secret_configured"] is True
    assert "test-secret" not in str(body)
