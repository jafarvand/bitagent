import math
from datetime import UTC, datetime
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator


class BookLevel(BaseModel):
    price: Decimal = Field(gt=0)
    quantity: Decimal = Field(gt=0)


class ExposureMetric(BaseModel):
    asset: str = Field(pattern=r"^[A-Z0-9]{2,20}$")
    value: Decimal = Field(ge=0)
    limit: Decimal = Field(gt=0)
    counterparty_class: str = Field(min_length=2, max_length=100)


class MarketRiskRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=100)
    market: str = Field(pattern=r"^[A-Z0-9]+_[A-Z0-9]+$")
    observed_at: datetime
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

    @model_validator(mode="after")
    def require_ordered_book(self):
        if self.bids != sorted(self.bids, key=lambda item: item.price, reverse=True):
            raise ValueError("bids must be ordered highest price first")
        if self.asks != sorted(self.asks, key=lambda item: item.price):
            raise ValueError("asks must be ordered lowest price first")
        if self.bids[0].price >= self.asks[0].price:
            raise ValueError("order book is crossed")
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
    band = Decimal("0.01")
    bid_depth = sum(level.price * level.quantity for level in request.bids
                    if level.price >= mid * (1 - band))
    ask_depth = sum(level.price * level.quantity for level in request.asks
                    if level.price <= mid * (1 + band))
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
        },
        "limit_breaches": breaches, "findings": findings,
        "market_quality_brief": {
            "headline": f"{request.market} market quality is {severity}.",
            "finding_count": len(findings), "limit_breach_count": len(breaches),
        },
        "limitations": ["Calculations use submitted venue evidence and are not causal proof."],
        "recommended_next_action": (
            "Escalate critical market or exposure findings for human review."
            if severity == "critical" else
            "Review warning thresholds and continue observation." if severity == "warning" else
            "Continue monitoring."
        ),
    }
