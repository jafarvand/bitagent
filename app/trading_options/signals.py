from __future__ import annotations

from dataclasses import dataclass

from .models import TradeAction, TradingSignal


@dataclass(slots=True)
class FeatureVector:
    momentum_5m: float = 0.0
    momentum_1h: float = 0.0
    rsi: float = 50.0
    orderbook_imbalance: float = 0.0
    volatility: float = 0.0


class BaselineSignalModel:
    """Transparent non-ML baseline used as a benchmark before XGBoost/RL.

    The point of this model is not sophistication; it creates a deterministic
    benchmark that later learned models must beat out-of-sample.
    """

    def __init__(self, trade_threshold: float = 0.22) -> None:
        self.trade_threshold = trade_threshold

    def predict(self, features: FeatureVector) -> TradingSignal:
        rsi_term = (features.rsi - 50.0) / 50.0
        score = (
            0.32 * _clip(features.momentum_5m * 20.0)
            + 0.28 * _clip(features.momentum_1h * 8.0)
            + 0.20 * _clip(rsi_term)
            + 0.20 * _clip(features.orderbook_imbalance)
        )

        # In very high volatility require a stronger signal rather than forcing a trade.
        threshold = self.trade_threshold + min(max(features.volatility, 0.0), 0.15)
        confidence = min(0.99, 0.5 + abs(score) / 2.0)

        if score >= threshold:
            action = TradeAction.CALL
        elif score <= -threshold:
            action = TradeAction.PUT
        else:
            action = TradeAction.NO_TRADE

        return TradingSignal(
            action=action,
            confidence=confidence,
            expected_return=score,
            reason=f"baseline score={score:.4f}; threshold={threshold:.4f}",
        )


def _clip(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, value))
