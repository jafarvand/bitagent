from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.trading_options.api import ledger, router


app = FastAPI()
app.include_router(router)
client = TestClient(app)


def setup_function():
    ledger.__init__(starting_cash=100_000.0)


def test_paper_order_and_mark_to_market():
    response = client.post(
        "/api/v0/options/paper-order",
        json={
            "symbol": "BTC-TEST-100000-C",
            "option_type": "CALL",
            "quantity": 2,
            "price": 100,
            "confidence": 0.9,
        },
    )
    assert response.status_code == 200
    assert response.json()["approved"] is True

    mark = client.post("/api/v0/options/mark?symbol=BTC-TEST-100000-C&price=120")
    assert mark.status_code == 200
    assert mark.json()["unrealized_pnl"] == 40

    pnl = client.get("/api/v0/options/pnl")
    assert pnl.status_code == 200
    assert pnl.json()["total_pnl"] == 40


def test_low_confidence_order_is_rejected():
    response = client.post(
        "/api/v0/options/paper-order",
        json={
            "symbol": "BTC-TEST-100000-P",
            "option_type": "PUT",
            "quantity": 1,
            "price": 100,
            "confidence": 0.2,
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["reason"] == "confidence below threshold"
