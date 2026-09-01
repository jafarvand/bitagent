from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Iterable


@dataclass(slots=True)
class Position:
    symbol: str
    quantity: float = 0.0
    avg_price: float = 0.0
    mark_price: float = 0.0
    realized_pnl: float = 0.0

    @property
    def market_value(self) -> float:
        return self.quantity * self.mark_price

    @property
    def unrealized_pnl(self) -> float:
        return self.quantity * (self.mark_price - self.avg_price)


@dataclass(slots=True)
class LedgerSnapshot:
    ts: datetime
    cash: float
    realized_pnl: float
    unrealized_pnl: float
    equity: float
    positions: list[Position] = field(default_factory=list)


class PaperPortfolioLedger:
    """Simple in-memory ledger for paper options execution.

    This intentionally stays deterministic and side-effect free so it can be
    replaced later by PostgreSQL/Timescale persistence without changing the
    trading service contract.
    """

    def __init__(self, starting_cash: float = 100_000.0) -> None:
        self.starting_cash = starting_cash
        self.cash = starting_cash
        self._positions: Dict[str, Position] = {}

    def apply_fill(self, *, symbol: str, quantity: float, price: float, fee: float = 0.0) -> Position:
        if quantity == 0:
            raise ValueError("quantity must be non-zero")
        if price < 0:
            raise ValueError("price must be non-negative")
        if fee < 0:
            raise ValueError("fee must be non-negative")

        pos = self._positions.setdefault(symbol, Position(symbol=symbol, mark_price=price))
        old_qty = pos.quantity
        new_qty = old_qty + quantity

        # Opening/increasing in the same direction: weighted average cost.
        if old_qty == 0 or old_qty * quantity > 0:
            gross_old = abs(old_qty) * pos.avg_price
            gross_new = abs(quantity) * price
            pos.avg_price = (gross_old + gross_new) / abs(new_qty)
        else:
            closing_qty = min(abs(quantity), abs(old_qty))
            direction = 1.0 if old_qty > 0 else -1.0
            pos.realized_pnl += closing_qty * (price - pos.avg_price) * direction
            # If the trade crosses through zero, the residual opens at fill price.
            if new_qty != 0 and old_qty * new_qty < 0:
                pos.avg_price = price
            elif new_qty == 0:
                pos.avg_price = 0.0

        pos.quantity = new_qty
        pos.mark_price = price
        self.cash -= quantity * price
        self.cash -= fee
        pos.realized_pnl -= fee
        return pos

    def mark(self, symbol: str, price: float) -> None:
        if price < 0:
            raise ValueError("price must be non-negative")
        if symbol in self._positions:
            self._positions[symbol].mark_price = price

    def mark_many(self, prices: dict[str, float]) -> None:
        for symbol, price in prices.items():
            self.mark(symbol, price)

    def positions(self) -> Iterable[Position]:
        return tuple(self._positions.values())

    def snapshot(self) -> LedgerSnapshot:
        positions = [p for p in self._positions.values() if p.quantity != 0]
        realized = sum(p.realized_pnl for p in self._positions.values())
        unrealized = sum(p.unrealized_pnl for p in positions)
        equity = self.cash + sum(p.market_value for p in positions)
        return LedgerSnapshot(
            ts=datetime.now(timezone.utc),
            cash=self.cash,
            realized_pnl=realized,
            unrealized_pnl=unrealized,
            equity=equity,
            positions=positions,
        )
