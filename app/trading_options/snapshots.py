from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .models import OptionInstrument


@dataclass(slots=True)
class MarketSnapshot:
    ts: datetime
    asset: str
    index_price: float | None
    instruments: list[OptionInstrument]

    @classmethod
    def now(
        cls,
        *,
        asset: str,
        instruments: list[OptionInstrument],
        index_price: float | None = None,
    ) -> "MarketSnapshot":
        return cls(
            ts=datetime.now(timezone.utc),
            asset=asset,
            index_price=index_price,
            instruments=instruments,
        )

    def marks(self) -> dict[str, float]:
        result: dict[str, float] = {}
        for instrument in self.instruments:
            if instrument.mark is not None:
                result[instrument.symbol] = instrument.mark
            elif instrument.bid is not None and instrument.ask is not None:
                result[instrument.symbol] = (instrument.bid + instrument.ask) / 2.0
        return result
