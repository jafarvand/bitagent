from datetime import UTC, datetime


def envelope(schema: str, data: dict, *, complete: bool = True, warnings: list[str] | None = None) -> dict:
    now = datetime.now(UTC).isoformat()
    return {
        "schema": {"name": schema, "version": "1.0.0"}, "tenant_id": "mock-exchange",
        "source_id": "synthetic-fixture", "owner": "bitagent-tests", "observed_at": now,
        "generated_at": now, "freshness_sla_seconds": 60, "data_class": "synthetic",
        "lineage": ["mock-data"], "quality": {"complete": complete, "warnings": warnings or []},
        "request_id": f"mock-{schema}", "data": data,
    }


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


def health() -> dict:
    return envelope("health", {"status": "healthy", "components": {
        "database": {"name": "mock-db", "type": "mysql", "status": "healthy", "latency_ms": 1},
        "matching_engine": {"name": "mock-core", "type": "matching-engine", "status": "healthy", "latency_ms": 2},
    }})


def transactions_summary() -> dict:
    return envelope("transactions.summary", {
        "as_of": datetime.now(UTC).isoformat(),
        "deposits": {"by_status": {"pending": 2, "processing": 1, "confirmed": 50, "rejected": 0, "unknown": 0}, "open_count": 3, "oldest_open_created_at": "2022-02-01 00:01:50", "oldest_open_age_seconds": 140000000},
        "withdrawals": {"by_status": {"pending": 2, "verified": 1, "processing": 1, "completed": 40, "cancelled": 1}, "open_count": 4, "oldest_open_created_at": "2022-06-26 05:41:49", "oldest_open_age_seconds": 130000000},
    })


def pending(kind: str) -> dict:
    is_withdrawal = kind == "withdrawals"
    item = ({"withdrawal_id": 1, "user_id": 10, "asset": "USDT", "network": "TRC20", "status": "processing", "process_status": 1, "requested_amount": "10", "sent_amount": "9", "fee": "1", "destination": "masked", "transaction_hash": None, "created_at": "2026-08-01 00:00:00", "updated_at": None, "age_seconds": 3600}
            if is_withdrawal else {"deposit_id": 2, "user_id": 10, "asset": "IRT", "network": "Shetab", "status": "pending", "collect_status": 0, "amount": "100", "net_amount": "100", "destination": None, "transaction_hash": None, "created_at": "2026-08-01 00:00:00", "updated_at": None, "age_seconds": 3600})
    return envelope(f"{kind}.pending", {"as_of": datetime.now(UTC).isoformat(), "count_returned": 1, "next_cursor": None, "items": [item]})


def liabilities() -> dict:
    return envelope("ledger.liabilities", {"ledger_snapshot_at": datetime.now(UTC).isoformat(), "asset_count": 2, "negative_balance_count": 0, "liabilities": [
        {"asset": "BTC", "available": "0.9", "locked": "0.1", "total": "1.0"},
        {"asset": "IRT", "available": "900", "locked": "100", "total": "1000"},
    ]})


def treasury_assets() -> dict:
    return envelope("treasury.assets", {"as_of": datetime.now(UTC).isoformat(), "crypto": {"assets": [
        {"asset": "BTC", "by_custody_class": {"cold": "1.1"}, "total": "1.1"}
    ], "wallets": []}, "fiat": {"total_irt": "1100", "accounts": []}})


def user_dataset(user_id: int, kind: str) -> dict:
    if kind == "summary":
        return envelope("userSummary", {"user_id": user_id, "account_status": "active", "registered_at": "2025-01-01 00:00:00", "kyc_level": 2, "operations": {"deposit_enabled": True, "withdraw_enabled": True, "fiat_deposit_enabled": True, "fiat_withdraw_enabled": True}, "orders": {"open": 1, "completed": 5}, "last_successful_login_at": None})
    if kind == "balances":
        return envelope("balances", {"user_id": user_id, "portfolio_value_irt": "1000", "items": [{"asset": "BTC"}]})
    if kind == "pnl":
        return envelope("pnl", {"user_id": user_id, "calculation_complete": False, "incomplete_reason": "weighted_average_ledger_not_connected", "execution_pnl": {"amount_irt": "10", "calculated_orders": 2, "calculated_at": None}})
    return envelope(kind, {"user_id": user_id, "date_from": "2026-07-01", "date_to": "2026-08-01", "items": [{f"{kind[:-1]}_id": 1}]})
