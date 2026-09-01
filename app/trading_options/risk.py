from __future__ import annotations

from dataclasses import dataclass

from .models import RiskDecision, TradeAction, TradingSignal


@dataclass(slots=True)
class RiskLimits:
    min_confidence: float = 0.65
    max_trade_fraction: float = 0.01
    max_daily_loss_fraction: float = 0.03
    max_drawdown_fraction: float = 0.10
    max_open_positions: int = 5


class RiskEngine:
    """Hard safety gate kept separate from model decisions."""

    def __init__(self, limits: RiskLimits | None = None) -> None:
        self.limits = limits or RiskLimits()

    def evaluate(
        self,
        signal: TradingSignal,
        *,
        daily_pnl_fraction: float,
        drawdown_fraction: float,
        open_positions: int,
    ) -> RiskDecision:
        if signal.action == TradeAction.NO_TRADE:
            return RiskDecision(False, "model selected NO_TRADE")
        if signal.confidence < self.limits.min_confidence:
            return RiskDecision(False, "confidence below threshold")
        if daily_pnl_fraction <= -self.limits.max_daily_loss_fraction:
            return RiskDecision(False, "daily loss limit reached")
        if drawdown_fraction >= self.limits.max_drawdown_fraction:
            return RiskDecision(False, "max drawdown limit reached")
        if open_positions >= self.limits.max_open_positions:
            return RiskDecision(False, "open position limit reached")
        return RiskDecision(True, "approved", self.limits.max_trade_fraction)
