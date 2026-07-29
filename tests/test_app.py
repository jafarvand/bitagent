from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health_is_read_only_version_zero():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["version"] == "0.0.1"


def test_dashboard_mock_contract():
    response = client.get("/api/v0/dashboard?market=BTC_USDT&days=30")
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "mock"
    assert body["operations"]["data"]["pending_withdrawals"] == 42
    assert body["market"]["data"]["market"] == "BTC_USDT"


def test_feature_gaps_are_explicit():
    response = client.get("/api/v0/features")
    assert response.status_code == 200
    body = response.json()
    assert body["counts"]["available"] >= 3
    assert body["counts"]["missing"] >= 1


def test_invalid_market_is_rejected():
    response = client.get("/api/v0/dashboard?market=bad-market")
    assert response.status_code == 422
