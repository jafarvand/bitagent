import math
from datetime import UTC, datetime
from decimal import Decimal

from pydantic import AwareDatetime, BaseModel, Field, model_validator


class BookLevel(BaseModel):
    price: Decimal = Field(gt=0)
    quantity: Decimal = Field(gt=0)


class ExposureMetric(BaseModel):
    asset: str = Field(pattern=r"^[A-Z0-9]{2,20}$")
    value: Decimal = Field(ge=0)
    limit: Decimal = Field(gt=0)
    counterparty_class: str = Field(min_length=2, max_length=100)
    valuation_source: str | None = Field(default=None, max_length=100)
    valuation_unavailable: bool = False


class TickerMetric(BaseModel):
    bid: Decimal = Field(gt=0)
    ask: Decimal = Field(gt=0)
    last: Decimal = Field(gt=0)
    venue: str = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_ticker(self):
        if self.bid >= self.ask:
            raise ValueError("ticker bid must be below ask")
        return self


class TradeMetric(BaseModel):
    trade_id: str = Field(min_length=1, max_length=100)
    occurred_at: AwareDatetime
    price: Decimal = Field(gt=0)
    quantity: Decimal = Field(gt=0)
    aggressor_side: str = Field(pattern=r"^(buy|sell|unknown)$")


class CandleMetric(BaseModel):
    open_time: AwareDatetime
    interval_seconds: int = Field(gt=0, le=86400)
    open: Decimal = Field(gt=0)
    high: Decimal = Field(gt=0)
    low: Decimal = Field(gt=0)
    close: Decimal = Field(gt=0)
    volume: Decimal = Field(ge=0)
    complete: bool

    @model_validator(mode="after")
    def validate_ohlc(self):
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ValueError("candle OHLC values are incoherent")
        if self.high < self.low:
            raise ValueError("candle high must not be below low")
        return self


class MarketLimitMetric(BaseModel):
    limit_id: str = Field(min_length=1, max_length=100)
    scope: str = Field(min_length=1, max_length=100)
    current_value: Decimal = Field(ge=0)
    threshold: Decimal = Field(gt=0)
    owner: str = Field(min_length=2, max_length=100)
    rationale: str = Field(min_length=3, max_length=500)


class MarketRiskRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=100)
    market: str = Field(pattern=r"^[A-Z0-9]+_[A-Z0-9]+$")
    observed_at: AwareDatetime
    evidence_refs: list[str] = Field(min_length=1, max_length=100)
    owner: str = Field(min_length=2, max_length=100)
    evidence_fresh: bool
    conflicting_fields: list[str] = Field(default_factory=list, max_length=100)
    bids: list[BookLevel] = Field(min_length=1, max_length=1000)
    asks: list[BookLevel] = Field(min_length=1, max_length=1000)
    recent_closes: list[Decimal] = Field(min_length=3, max_length=1000)
    current_volume: Decimal = Field(ge=0)
    baseline_volume: Decimal = Field(gt=0)
    reference_price: Decimal = Field(gt=0)
    exposures: list[ExposureMetric] = Field(min_length=1, max_length=1000)
    book_sequence: int | None = Field(default=None, ge=0)
    snapshot_id: str | None = Field(default=None, max_length=100)
    ticker: TickerMetric | None = None
    trades: list[TradeMetric] = Field(default_factory=list, max_length=5000)
    candles: list[CandleMetric] = Field(default_factory=list, max_length=5000)
    depth_bands_bps: list[int] = Field(default=[10, 50, 100], min_length=1, max_length=10)
    market_limits: list[MarketLimitMetric] = Field(default_factory=list, max_length=1000)

    @model_validator(mode="after")
    def require_ordered_book(self):
        if self.bids != sorted(self.bids, key=lambda item: item.price, reverse=True):
            raise ValueError("bids must be ordered highest price first")
        if self.asks != sorted(self.asks, key=lambda item: item.price):
            raise ValueError("asks must be ordered lowest price first")
        if self.bids[0].price >= self.asks[0].price:
            raise ValueError("order book is crossed")
        if sorted(set(self.depth_bands_bps)) != self.depth_bands_bps:
            raise ValueError("depth_bands_bps must be unique and increasing")
        if any(value < 1 or value > 5000 for value in self.depth_bands_bps):
            raise ValueError("depth bands must be between 1 and 5000 bps")
        if self.trades != sorted(self.trades, key=lambda item: item.occurred_at):
            raise ValueError("trades must be ordered by occurred_at")
        if self.candles != sorted(self.candles, key=lambda item: item.open_time):
            raise ValueError("candles must be ordered by open_time")
        return self


def _decimal(value: Decimal, places: str = "0.01") -> str:
    return str(value.quantize(Decimal(places)))


def analyze_market_risk(request: MarketRiskRequest) -> dict:
    analyzed_at = datetime.now(UTC).isoformat()
    common = {
        "tenant_id": request.tenant_id, "market": request.market,
        "observed_at": request.observed_at.isoformat(), "analyzed_at": analyzed_at,
        "evidence_refs": request.evidence_refs, "owner": request.owner,
        "action_executed": False,
    }
    if not request.evidence_fresh or request.conflicting_fields:
        return {
            **common, "status": "blocked", "severity": "unknown", "confidence": "none",
            "metrics": {}, "findings": [],
            "limitations": (
                (["stale evidence"] if not request.evidence_fresh else []) +
                ([f"conflicting fields: {', '.join(request.conflicting_fields)}"]
                 if request.conflicting_fields else [])
            ),
            "recommended_next_action": "Refresh and reconcile market evidence.",
        }

    best_bid, best_ask = request.bids[0].price, request.asks[0].price
    mid = (best_bid + best_ask) / 2
    spread_bps = (best_ask - best_bid) / mid * Decimal("10000")
    depth_bands = {}
    for band_bps in request.depth_bands_bps:
        band = Decimal(band_bps) / Decimal("10000")
        depth_bands[str(band_bps)] = {
            "bid": sum((level.price * level.quantity for level in request.bids
                        if level.price >= mid * (1 - band)), Decimal("0")),
            "ask": sum((level.price * level.quantity for level in request.asks
                        if level.price <= mid * (1 + band)), Decimal("0")),
        }
    primary_band = depth_bands[str(max(request.depth_bands_bps))]
    bid_depth, ask_depth = primary_band["bid"], primary_band["ask"]
    returns = [
        float((current - previous) / previous)
        for previous, current in zip(request.recent_closes, request.recent_closes[1:])
        if previous
    ]
    mean_return = sum(returns) / len(returns)
    volatility_percent = math.sqrt(
        sum((value - mean_return) ** 2 for value in returns) / len(returns)
    ) * 100
    volume_multiple = request.current_volume / request.baseline_volume
    deviation_percent = abs(mid - request.reference_price) / request.reference_price * 100
    total_exposure = sum((item.value for item in request.exposures), Decimal("0"))
    largest = max(request.exposures, key=lambda item: item.value)
    concentration_percent = largest.value / total_exposure * 100 if total_exposure else Decimal("0")
    breaches = [
        {"asset": item.asset, "value": _decimal(item.value), "limit": _decimal(item.limit),
         "utilization_percent": _decimal(item.value / item.limit * 100),
         "explanation": "Submitted exposure exceeds the configured deterministic limit."}
        for item in request.exposures if item.value > item.limit
    ]
    market_limit_results = [
        {"limit_id": item.limit_id, "scope": item.scope,
         "current_value": str(item.current_value), "threshold": str(item.threshold),
         "utilization_percent": _decimal(item.current_value / item.threshold * 100),
         "state": "breached" if item.current_value > item.threshold else
                  "warning" if item.current_value / item.threshold >= Decimal("0.8") else "within_limit",
         "owner": item.owner, "rationale": item.rationale}
        for item in request.market_limits
    ]
    buy_notional = sum((item.price * item.quantity for item in request.trades
                        if item.aggressor_side == "buy"), Decimal("0"))
    sell_notional = sum((item.price * item.quantity for item in request.trades
                         if item.aggressor_side == "sell"), Decimal("0"))
    known_notional = buy_notional + sell_notional
    trade_imbalance_percent = ((buy_notional - sell_notional) / known_notional * 100
                               if known_notional else Decimal("0"))
    candle_gap_count = sum(
        1 for previous, current in zip(request.candles, request.candles[1:])
        if int((current.open_time - previous.open_time).total_seconds()) != previous.interval_seconds
    )
    incomplete_candle_count = sum(not item.complete for item in request.candles)
    ticker_deviation_bps = None
    if request.ticker:
        ticker_mid = (request.ticker.bid + request.ticker.ask) / 2
        ticker_deviation_bps = abs(ticker_mid - mid) / mid * Decimal("10000")
    findings = []
    if spread_bps >= 100:
        findings.append({"type": "wide_spread", "severity": "critical", "value": _decimal(spread_bps)})
    elif spread_bps >= 50:
        findings.append({"type": "wide_spread", "severity": "warning", "value": _decimal(spread_bps)})
    if min(bid_depth, ask_depth) < Decimal("10000"):
        findings.append({"type": "thin_depth", "severity": "warning",
                         "value": _decimal(min(bid_depth, ask_depth))})
    if volatility_percent >= 10:
        findings.append({"type": "high_volatility", "severity": "critical",
                         "value": f"{volatility_percent:.2f}"})
    elif volatility_percent >= 5:
        findings.append({"type": "high_volatility", "severity": "warning",
                         "value": f"{volatility_percent:.2f}"})
    if volume_multiple >= 3:
        findings.append({"type": "abnormal_volume", "severity": "warning",
                         "value": _decimal(volume_multiple)})
    if deviation_percent >= 10:
        findings.append({"type": "reference_divergence", "severity": "critical",
                         "value": _decimal(deviation_percent)})
    if concentration_percent >= 50:
        findings.append({"type": "exposure_concentration", "severity": "warning",
                         "asset": largest.asset, "value": _decimal(concentration_percent)})
    findings.extend({"type": "limit_breach", "severity": "critical", **breach} for breach in breaches)
    findings.extend({"type": "market_limit", "severity": "critical" if item["state"] == "breached" else "warning", **item}
                    for item in market_limit_results if item["state"] != "within_limit")
    if ticker_deviation_bps is not None and ticker_deviation_bps >= 25:
        findings.append({"type": "ticker_book_divergence", "severity": "warning",
                         "value": _decimal(ticker_deviation_bps)})
    if abs(trade_imbalance_percent) >= 70 and known_notional:
        findings.append({"type": "aggressor_imbalance", "severity": "warning",
                         "value": _decimal(trade_imbalance_percent)})
    if candle_gap_count:
        findings.append({"type": "candle_gaps", "severity": "warning", "value": candle_gap_count})
    if any(item.valuation_unavailable for item in request.exposures):
        findings.append({"type": "unavailable_valuation", "severity": "critical",
                         "value": sum(item.valuation_unavailable for item in request.exposures)})
    severity = "critical" if any(item["severity"] == "critical" for item in findings) else (
        "warning" if findings else "healthy"
    )
    return {
        **common, "status": "ready", "severity": severity, "confidence": "high",
        "metrics": {
            "best_bid": str(best_bid), "best_ask": str(best_ask), "mid": _decimal(mid),
            "spread_bps": _decimal(spread_bps), "bid_depth_100bps": _decimal(bid_depth),
            "ask_depth_100bps": _decimal(ask_depth),
            "return_volatility_percent": f"{volatility_percent:.2f}",
            "volume_multiple": _decimal(volume_multiple),
            "reference_deviation_percent": _decimal(deviation_percent),
            "total_exposure": _decimal(total_exposure),
            "largest_exposure_asset": largest.asset,
            "concentration_percent": _decimal(concentration_percent),
            "depth_bands": {band: {side: _decimal(value) for side, value in values.items()}
                            for band, values in depth_bands.items()},
            "book_sequence": request.book_sequence, "snapshot_id": request.snapshot_id,
            "trade_count": len(request.trades),
            "aggressor_imbalance_percent": _decimal(trade_imbalance_percent),
            "candle_count": len(request.candles), "candle_gap_count": candle_gap_count,
            "incomplete_candle_count": incomplete_candle_count,
            "ticker_book_deviation_bps": (_decimal(ticker_deviation_bps)
                                            if ticker_deviation_bps is not None else None),
        },
        "limit_breaches": breaches, "market_limits": market_limit_results, "findings": findings,
        "market_quality_brief": {
            "headline": f"{request.market} market quality is {severity}.",
            "finding_count": len(findings), "limit_breach_count": len(breaches),
        },
        "limitations": (["Calculations use submitted venue evidence and are not causal proof."] +
                        (["Order-book sequence or snapshot ID is unavailable."]
                         if request.book_sequence is None or request.snapshot_id is None else []) +
                        (["No normalized trade evidence was supplied."] if not request.trades else []) +
                        (["No normalized candle evidence was supplied."] if not request.candles else [])),
        "recommended_next_action": (
            "Escalate critical market or exposure findings for human review."
            if severity == "critical" else
            "Review warning thresholds and continue observation." if severity == "warning" else
            "Continue monitoring."
        ),
    }
