from __future__ import annotations

from dataclasses import dataclass

from .connectors.aevo import AevoPublicClient
from .models import OptionInstrument, TradeAction, TradingSignal
from .paper import PaperExecutor, PaperFill
from .risk import RiskEngine


@dataclass(slots=True)
class TradingContext:
    daily_pnl_fraction: float = 0.0
    drawdown_fraction: float = 0.0
    open_positions: int = 0


class OptionsTradingService:
    """M1 orchestration layer: market data -> signal -> risk -> paper fill."""

    def __init__(
        self,
        market: AevoPublicClient,
        risk: RiskEngine | None = None,
        executor: PaperExecutor | None = None,
    ) -> None:
        self.market = market
        self.risk = risk or RiskEngine()
        self.executor = executor or PaperExecutor()

    async def btc_options(self) -> list[OptionInstrument]:
        return await self.market.list_options("BTC")

    def dummy_signal(self, action: TradeAction, confidence: float = 0.70) -> TradingSignal:
        """Temporary deterministic signal used only to validate M1 plumbing."""
        return TradingSignal(
            action=action,
            confidence=confidence,
            expected_return=0.0,
            reason="M1 plumbing signal; replace with baseline model in M2",
        )

    def paper_trade(
        self,
        signal: TradingSignal,
        instrument: OptionInstrument,
        context: TradingContext | None = None,
        requested_fraction: float = 0.01,
    ) -> PaperFill | None:
        ctx = context or TradingContext()
        decision = self.risk.evaluate(
            signal,
            daily_pnl_fraction=ctx.daily_pnl_fraction,
            drawdown_fraction=ctx.drawdown_fraction,
            open_positions=ctx.open_positions,
        )
        return self.executor.execute_buy(signal, instrument, decision, requested_fraction)
