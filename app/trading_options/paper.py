from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from .models import OptionInstrument, RiskDecision, TradeAction, TradingSignal


@dataclass(slots=True)
class PaperFill:
    fill_id: str
    timestamp: str
    symbol: str
    action: TradeAction
    quantity: float
    price: float
    notional: float
    fee: float
    reason: str


@dataclass(slots=True)
class PaperPortfolio:
    starting_equity: float = 10_000.0
    cash: float = 10_000.0
    realized_pnl: float = 0.0
    fills: list[PaperFill] = field(default_factory=list)

    @property
    def equity(self) -> float:
        return self.cash


class PaperExecutor:
    """Deterministic M1 execution simulator.

    It does not try to mimic a full matching engine. A buy is filled at ask +
    configured slippage and immediately booked as premium spent. Mark-to-market
    and closing logic are intentionally deferred to the backtest/PnL milestone.
    """

    def __init__(self, portfolio: PaperPortfolio | None = None, fee_bps: float = 5.0, slippage_bps: float = 10.0):
        self.portfolio = portfolio or PaperPortfolio()
        self.fee_bps = fee_bps
        self.slippage_bps = slippage_bps

    def execute_buy(
        self,
        signal: TradingSignal,
        instrument: OptionInstrument,
        risk: RiskDecision,
        requested_fraction: float,
    ) -> PaperFill | None:
        if signal.action == TradeAction.NO_TRADE or not risk.approved:
            return None
        if signal.action.value != instrument.option_type:
            raise ValueError("signal action does not match option instrument type")
        if requested_fraction <= 0:
            raise ValueError("requested_fraction must be positive")
        if instrument.ask is None or instrument.ask <= 0:
            raise ValueError("instrument requires a positive ask price for paper execution")

        fraction = min(requested_fraction, risk.max_position_fraction)
        budget = self.portfolio.equity * fraction
        fill_price = instrument.ask * (1.0 + self.slippage_bps / 10_000.0)
        quantity = budget / fill_price
        notional = quantity * fill_price
        fee = notional * self.fee_bps / 10_000.0
        total_cost = notional + fee

        if total_cost > self.portfolio.cash:
            quantity = self.portfolio.cash / (fill_price * (1.0 + self.fee_bps / 10_000.0))
            notional = quantity * fill_price
            fee = notional * self.fee_bps / 10_000.0
            total_cost = notional + fee

        if quantity <= 0:
            return None

        self.portfolio.cash -= total_cost
        fill = PaperFill(
            fill_id=str(uuid4()),
            timestamp=datetime.now(timezone.utc).isoformat(),
            symbol=instrument.symbol,
            action=signal.action,
            quantity=quantity,
            price=fill_price,
            notional=notional,
            fee=fee,
            reason=signal.reason,
        )
        self.portfolio.fills.append(fill)
        return fill
