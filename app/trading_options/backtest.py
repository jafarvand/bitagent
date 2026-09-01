from __future__ import annotations

from dataclasses import dataclass, field
from math import sqrt
from statistics import mean, pstdev
from typing import Iterable

from .models import TradeAction, TradingSignal


@dataclass(slots=True)
class BacktestBar:
    ts: int
    price: float
    future_price: float
    volatility: float = 0.0


@dataclass(slots=True)
class BacktestTrade:
    ts: int
    action: TradeAction
    entry: float
    exit: float
    pnl_fraction: float
    confidence: float


@dataclass(slots=True)
class BacktestResult:
    trades: list[BacktestTrade] = field(default_factory=list)
    total_return: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    max_drawdown: float = 0.0
    sharpe: float = 0.0
    expectancy: float = 0.0


def label_direction(current: float, future: float, threshold: float = 0.008) -> TradeAction:
    if current <= 0:
        raise ValueError("current price must be positive")
    ret = future / current - 1.0
    if ret >= threshold:
        return TradeAction.CALL
    if ret <= -threshold:
        return TradeAction.PUT
    return TradeAction.NO_TRADE


def directional_pnl(action: TradeAction, entry: float, exit: float) -> float:
    if entry <= 0:
        raise ValueError("entry must be positive")
    underlying_return = exit / entry - 1.0
    if action == TradeAction.CALL:
        return underlying_return
    if action == TradeAction.PUT:
        return -underlying_return
    return 0.0


def run_backtest(
    bars: Iterable[BacktestBar],
    signals: Iterable[TradingSignal],
    *,
    fee_fraction: float = 0.0005,
) -> BacktestResult:
    bars_list = list(bars)
    signal_list = list(signals)
    if len(bars_list) != len(signal_list):
        raise ValueError("bars and signals must have the same length")

    trades: list[BacktestTrade] = []
    returns: list[float] = []
    equity = 1.0
    peak = 1.0
    max_dd = 0.0

    for bar, signal in zip(bars_list, signal_list):
        if signal.action == TradeAction.NO_TRADE:
            continue
        gross = directional_pnl(signal.action, bar.price, bar.future_price)
        net = gross - fee_fraction
        trades.append(
            BacktestTrade(
                ts=bar.ts,
                action=signal.action,
                entry=bar.price,
                exit=bar.future_price,
                pnl_fraction=net,
                confidence=signal.confidence,
            )
        )
        returns.append(net)
        equity *= 1.0 + net
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak)

    if not trades:
        return BacktestResult()

    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = gross_profit / gross_loss if gross_loss else float("inf")
    sigma = pstdev(returns) if len(returns) > 1 else 0.0
    sharpe = mean(returns) / sigma * sqrt(len(returns)) if sigma > 0 else 0.0

    return BacktestResult(
        trades=trades,
        total_return=equity - 1.0,
        win_rate=len(wins) / len(trades),
        profit_factor=profit_factor,
        max_drawdown=max_dd,
        sharpe=sharpe,
        expectancy=mean(returns),
    )
