from datetime import UTC, datetime


def operations(days: int) -> dict:
    now = datetime.now(UTC)
    return {
        "data": {
            "date_from": f"{days} days ago",
            "date_to": now.isoformat(),
            "orders": 261,
            "deposits": 60,
            "withdrawals": 203,
            "pending_withdrawals": 42,
            "failed_deposits": 0,
            "fee_revenue_by_asset": {
                "USDT": "8.36989817",
                "IRT": "1995095.77433421",
                "BTC": "0.00003376",
            },
        },
        "meta": {
            "request_id": "mock-operations",
            "generated_at": now.isoformat(),
            "currency": "IRT",
            "data_freshness_seconds": 0,
        },
    }


def market(symbol: str) -> dict:
    now = datetime.now(UTC).isoformat()
    base, _, quote = symbol.partition("_")
    return {
        "data": {
            "market": symbol,
            "is_active": True,
            "base_asset": base or "BTC",
            "quote_asset": quote or "USDT",
            "last": "63836.85000000",
            "open": "63120.00000000",
            "high": "64510.00000000",
            "low": "62790.00000000",
            "volume": "18.42000000",
            "as_of": now,
        },
        "meta": {
            "request_id": "mock-market",
            "generated_at": now,
            "currency": "IRT",
            "data_freshness_seconds": 0,
        },
    }
