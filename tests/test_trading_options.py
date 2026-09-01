import json

import httpx
import pytest

from app.trading_options.connectors.aevo import AevoConfig, AevoPublicClient
from app.trading_options.models import OptionInstrument, TradeAction, TradingSignal
from app.trading_options.paper import PaperExecutor, PaperPortfolio
from app.trading_options.risk import RiskEngine
from app.trading_options.service import OptionsTradingService


@pytest.mark.asyncio
async def test_aevo_public_client_parses_btc_options():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/markets"
        assert request.url.params["asset"] == "BTC"
        return httpx.Response(
            200,
            json=[
                {
                    "instrument_name": "BTC-30SEP26-100000-C",
                    "instrument_type": "OPTION",
                    "strike": "100000",
                    "expiry": 1790726400,
                    "best_bid": "2100",
                    "best_ask": "2150",
                    "mark_price": "2125",
                },
                {
                    "instrument_name": "BTC-PERP",
                    "instrument_type": "PERPETUAL",
                },
            ],
        )

    async with httpx.AsyncClient(
        base_url="https://api-testnet.aevo.xyz",
        transport=httpx.MockTransport(handler),
    ) as http:
        client = AevoPublicClient(AevoConfig(env="testnet"), client=http)
        options = await client.list_options("BTC")

    assert len(options) == 1
    assert options[0].option_type == "CALL"
    assert options[0].strike == 100000.0
    assert options[0].ask == 2150.0


def test_risk_gate_blocks_low_confidence():
    decision = RiskEngine().evaluate(
        TradingSignal(TradeAction.CALL, confidence=0.50),
        daily_pnl_fraction=0,
        drawdown_fraction=0,
        open_positions=0,
    )
    assert decision.approved is False
    assert "confidence" in decision.reason


def test_paper_trade_respects_risk_position_limit():
    portfolio = PaperPortfolio(starting_equity=10_000.0, cash=10_000.0)
    executor = PaperExecutor(portfolio, fee_bps=0, slippage_bps=0)
    service = OptionsTradingService(
        market=None,  # type: ignore[arg-type]
        executor=executor,
    )
    instrument = OptionInstrument(
        symbol="BTC-30SEP26-100000-C",
        underlying="BTC",
        option_type="CALL",
        strike=100000,
        expiry_ts=1790726400,
        bid=2000,
        ask=2100,
        mark=2050,
    )
    fill = service.paper_trade(
        TradingSignal(TradeAction.CALL, confidence=0.90, reason="test"),
        instrument,
        requested_fraction=0.25,
    )

    assert fill is not None
    assert fill.notional == pytest.approx(100.0)
    assert portfolio.cash == pytest.approx(9900.0)


def test_paper_executor_rejects_signal_instrument_mismatch():
    executor = PaperExecutor(fee_bps=0, slippage_bps=0)
    instrument = OptionInstrument(
        symbol="BTC-30SEP26-100000-P",
        underlying="BTC",
        option_type="PUT",
        strike=100000,
        expiry_ts=1790726400,
        ask=1000,
    )
    decision = RiskEngine().evaluate(
        TradingSignal(TradeAction.CALL, confidence=0.90),
        daily_pnl_fraction=0,
        drawdown_fraction=0,
        open_positions=0,
    )
    with pytest.raises(ValueError, match="does not match"):
        executor.execute_buy(
            TradingSignal(TradeAction.CALL, confidence=0.90),
            instrument,
            decision,
            requested_fraction=0.01,
        )
