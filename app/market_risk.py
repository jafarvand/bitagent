from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


RULE_ID = "market-range-percent"
RULE_VERSION = "1.0.0"
TWO_PLACES = Decimal("0.01")


def _decimal(value: object) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def analyze_market_range(
    market_response: dict,
    *,
    warning_percent: Decimal,
    critical_percent: Decimal,
) -> dict:
    """Calculate a bounded market-range signal without inferring liquidity."""
    data = market_response.get("data", {})
    meta = market_response.get("meta", {})
    low = _decimal(data.get("low"))
    high = _decimal(data.get("high"))
    last = _decimal(data.get("last"))

    missing_or_invalid_fields = []
    if low is None or low <= 0:
        missing_or_invalid_fields.append("low")
    if high is None or high <= 0:
        missing_or_invalid_fields.append("high")
    if last is None or last <= 0:
        missing_or_invalid_fields.append("last")
    if low is not None and high is not None and high < low:
        missing_or_invalid_fields.append("high_below_low")
    valid = not missing_or_invalid_fields
    if valid:
        range_percent = ((high - low) / low * 100).quantize(
            TWO_PLACES, rounding=ROUND_HALF_UP
        )
        position_percent = (
            ((last - low) / (high - low) * 100).quantize(
                TWO_PLACES, rounding=ROUND_HALF_UP
            )
            if high > low
            else Decimal("0.00")
        )
        position_percent = max(Decimal("0"), min(Decimal("100"), position_percent))
        severity = (
            "critical"
            if range_percent >= critical_percent
            else "warning"
            if range_percent >= warning_percent
            else "healthy"
        )
    else:
        range_percent = position_percent = None
        severity = "unknown"

    return {
        "rule": {"id": RULE_ID, "version": RULE_VERSION},
        "market": data.get("market"),
        "severity": severity,
        "metrics": {
            "range_percent": str(range_percent) if range_percent is not None else None,
            "last_position_percent": (
                str(position_percent) if position_percent is not None else None
            ),
            "low": str(low) if low is not None else None,
            "high": str(high) if high is not None else None,
            "last": str(last) if last is not None else None,
        },
        "thresholds": {
            "warning_range_percent": str(warning_percent),
            "critical_range_percent": str(critical_percent),
        },
        "evidence": {
            "source": "GET /api/bot/market/{market}/summary",
            "request_id": meta.get("request_id"),
            "generated_at": meta.get("generated_at"),
            "data_freshness_seconds": meta.get("data_freshness_seconds"),
        },
        "confidence": "bounded" if valid else "insufficient",
        "data_quality": {
            "valid": valid,
            "missing_or_invalid_fields": missing_or_invalid_fields,
        },
        "limitations": [
            "This is an observed high-low range, not statistical volatility.",
            "Spread, order-book depth and reference-price divergence are unavailable.",
            "No exposure, position or treasury data is included.",
        ],
        "action_executed": False,
    }
