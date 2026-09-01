from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .connectors.aevo import AevoPublicClient
from .ledger import PaperPortfolioLedger
from .models import OptionInstrument, TradeAction, TradingSignal
from .risk import RiskEngine

router = APIRouter(prefix="/api/v0/options", tags=["options-paper"])
ledger = PaperPortfolioLedger(starting_cash=100_000.0)
risk_engine = RiskEngine()


class PaperOrderRequest(BaseModel):
    symbol: str
    option_type: TradeAction
    quantity: float = Field(gt=0)
    price: float = Field(gt=0)
    confidence: float = Field(ge=0, le=1)
    daily_pnl_fraction: float = 0.0
    drawdown_fraction: float = Field(default=0.0, ge=0)
    open_positions: int = Field(default=0, ge=0)
    reason: str = "manual paper order"


@router.get("/markets")
async def option_markets(asset: str = Query(default="BTC", min_length=2, max_length=12)):
    client = AevoPublicClient()
    try:
        options = await client.list_options(asset)
        return {"asset": asset.upper(), "count": len(options), "markets": [asdict(item) for item in options]}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Aevo market data unavailable: {exc}") from exc
    finally:
        await client.aclose()


@router.get("/portfolio")
def option_portfolio():
    snap = ledger.snapshot()
    return {
        "ts": snap.ts.isoformat(),
        "cash": snap.cash,
        "equity": snap.equity,
        "realized_pnl": snap.realized_pnl,
        "unrealized_pnl": snap.unrealized_pnl,
        "positions": [asdict(position) for position in snap.positions],
    }


@router.get("/pnl")
def option_pnl():
    snap = ledger.snapshot()
    return {
        "realized_pnl": snap.realized_pnl,
        "unrealized_pnl": snap.unrealized_pnl,
        "total_pnl": snap.equity - ledger.starting_cash,
        "equity": snap.equity,
    }


@router.post("/paper-order")
def option_paper_order(order: PaperOrderRequest):
    if order.option_type == TradeAction.NO_TRADE:
        raise HTTPException(status_code=400, detail="NO_TRADE cannot create an order")

    signal = TradingSignal(
        action=order.option_type,
        confidence=order.confidence,
        reason=order.reason,
    )
    decision = risk_engine.evaluate(
        signal,
        daily_pnl_fraction=order.daily_pnl_fraction,
        drawdown_fraction=order.drawdown_fraction,
        open_positions=order.open_positions,
    )
    if not decision.approved:
        raise HTTPException(status_code=409, detail={"approved": False, "reason": decision.reason})

    position = ledger.apply_fill(
        symbol=order.symbol,
        quantity=order.quantity,
        price=order.price,
    )
    snap = ledger.snapshot()
    return {
        "approved": True,
        "risk": asdict(decision),
        "position": asdict(position),
        "equity": snap.equity,
        "cash": snap.cash,
    }


@router.post("/mark")
def option_mark(symbol: str, price: float = Query(gt=0)):
    ledger.mark(symbol, price)
    snap = ledger.snapshot()
    return {
        "symbol": symbol,
        "price": price,
        "equity": snap.equity,
        "unrealized_pnl": snap.unrealized_pnl,
    }
