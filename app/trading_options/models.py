from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class TradeAction(str, Enum):
    CALL = "CALL"
    PUT = "PUT"
    NO_TRADE = "NO_TRADE"


@dataclass(slots=True)
class TradingSignal:
    action: TradeAction
    confidence: float
    expected_return: float = 0.0
    reason: str = ""


@dataclass(slots=True)
class RiskDecision:
    approved: bool
    reason: str
    max_position_fraction: float = 0.0


@dataclass(slots=True)
class OptionInstrument:
    symbol: str
    underlying: str
    option_type: str
    strike: float
    expiry_ts: int
    bid: Optional[float] = None
    ask: Optional[float] = None
    mark: Optional[float] = None
