from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation


REQUIRED_ENVELOPE_FIELDS = {
    "schema", "tenant_id", "source_id", "owner", "observed_at", "generated_at",
    "freshness_sla_seconds", "data_class", "lineage", "quality", "request_id", "data",
}


class ExchangeContractError(ValueError):
    pass


def validate_envelope(payload: dict, expected_schema: str) -> dict:
    missing = sorted(REQUIRED_ENVELOPE_FIELDS - payload.keys())
    if missing:
        raise ExchangeContractError(f"missing envelope fields: {', '.join(missing)}")
    schema = payload.get("schema", {})
    if schema.get("name") != expected_schema or not schema.get("version"):
        raise ExchangeContractError(
            f"expected schema {expected_schema}, received {schema.get('name') or 'unknown'}"
        )
    if not isinstance(payload.get("data"), dict):
        raise ExchangeContractError("envelope data must be an object")
    return payload


def _decimal(value, field: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError) as exc:
        raise ExchangeContractError(f"invalid decimal at {field}") from exc


def analyze_transaction_flow(
    health: dict, transactions: dict, withdrawals: dict, deposits: dict,
) -> dict:
    validate_envelope(health, "health")
    validate_envelope(transactions, "transactions.summary")
    validate_envelope(withdrawals, "withdrawals.pending")
    validate_envelope(deposits, "deposits.pending")
    health_data = health["data"]
    tx = transactions["data"]
    withdrawal_items = withdrawals["data"].get("items", [])
    deposit_items = deposits["data"].get("items", [])
    stale_caveat = any(
        (side.get("oldest_open_age_seconds") or 0) > 365 * 24 * 3600
        for side in (tx.get("withdrawals", {}), tx.get("deposits", {}))
    )
    unknown_deposit_statuses = sum(
        1 for item in deposit_items if item.get("status") not in {"pending", "processing"}
    )
    return {
        "status": "ready",
        "exchange_status": health_data.get("status", "unknown"),
        "components": health_data.get("components", {}),
        "open_counts": {
            "withdrawals": tx["withdrawals"]["open_count"],
            "deposits": tx["deposits"]["open_count"],
        },
        "sample": {
            "withdrawals_returned": withdrawals["data"].get("count_returned", len(withdrawal_items)),
            "deposits_returned": deposits["data"].get("count_returned", len(deposit_items)),
            "withdrawal_next_cursor": withdrawals["data"].get("next_cursor"),
            "deposit_next_cursor": deposits["data"].get("next_cursor"),
            "withdrawals_by_asset": _counts(withdrawal_items, "asset"),
            "withdrawals_by_network": _counts(withdrawal_items, "network"),
            "deposits_by_asset": _counts(deposit_items, "asset"),
            "deposits_by_network": _counts(deposit_items, "network"),
        },
        "data_quality": {
            "stale_legacy_rows_possible": stale_caveat,
            "unknown_deposit_statuses": unknown_deposit_statuses,
            "complete": all(
                item.get("quality", {}).get("complete", False)
                for item in (health, transactions, withdrawals, deposits)
            ),
            "warnings": sum(
                (item.get("quality", {}).get("warnings", []) for item in
                 (health, transactions, withdrawals, deposits)), []
            ),
        },
        "limitations": [
            "Raw four-year-old open rows are not treated as a live incident.",
            "Queue, worker, confirmation, retry, and normalized reason evidence remain unavailable.",
        ],
        "action_executed": False,
    }


def _counts(items: list[dict], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = item.get(field)
        key = str(value) if value not in (None, "") else "unknown"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def reconcile_treasury(liabilities: dict, treasury: dict) -> dict:
    validate_envelope(liabilities, "ledger.liabilities")
    validate_envelope(treasury, "treasury.assets")
    liability_data = liabilities["data"]
    treasury_data = treasury["data"]
    liability_by_asset = {
        item["asset"]: _decimal(item["total"], f"liabilities.{item['asset']}.total")
        for item in liability_data.get("liabilities", [])
    }
    controlled_by_asset = {
        item["asset"]: _decimal(item["total"], f"treasury.{item['asset']}.total")
        for item in treasury_data.get("crypto", {}).get("assets", [])
    }
    fiat_total = treasury_data.get("fiat", {}).get("total_irt")
    if fiat_total is not None:
        controlled_by_asset["IRT"] = controlled_by_asset.get("IRT", Decimal(0)) + _decimal(
            fiat_total, "treasury.fiat.total_irt"
        )
    assets = sorted(liability_by_asset.keys() | controlled_by_asset.keys())
    positions = []
    for asset in assets:
        liability = liability_by_asset.get(asset, Decimal(0))
        controlled = controlled_by_asset.get(asset, Decimal(0))
        difference = controlled - liability
        positions.append({
            "asset": asset,
            "controlled_assets": str(controlled),
            "customer_liabilities": str(liability),
            "difference": str(difference),
            "coverage_percent": str((controlled / liability * 100).quantize(Decimal("0.01"))) if liability else None,
            "deficit": difference < 0,
            "source_complete": treasury.get("quality", {}).get("complete", False),
        })
    incomplete = not treasury.get("quality", {}).get("complete", False)
    deficits = [item["asset"] for item in positions if item["deficit"]]
    return {
        "status": "partial" if incomplete else "ready",
        "severity": "unknown" if incomplete else "critical" if deficits else "healthy",
        "ledger_snapshot_at": liability_data.get("ledger_snapshot_at"),
        "treasury_as_of": treasury_data.get("as_of"),
        "negative_balance_count": liability_data.get("negative_balance_count", 0),
        "positions": positions,
        "deficit_assets": deficits,
        "quality": {
            "complete": not incomplete,
            "warnings": treasury.get("quality", {}).get("warnings", []),
            "manual_wallet_refresh_required": True,
        },
        "limitations": [
            "Treasury wallet balances are manually refreshed and can be stale.",
            "This comparison is operational evidence, not audited proof of reserves.",
            "No funds, balances, or ledger entries were changed.",
        ],
        "generated_at": datetime.now(UTC).isoformat(),
        "action_executed": False,
    }


def summarize_user_investigation(
    summary: dict | None, balances: dict | None, trades: dict | None,
    deposits: dict | None, withdrawals: dict | None, pnl: dict | None,
    source_errors: dict[str, str] | None = None,
) -> dict:
    expected = ["userSummary", "balances", "trades", "deposits", "withdrawals", "pnl"]
    payloads = [summary, balances, trades, deposits, withdrawals, pnl]
    for payload, schema in zip(payloads, expected):
        if payload is not None:
            validate_envelope(payload, schema)
    if summary is None:
        raise ExchangeContractError("user summary is required for an investigation")
    user = summary["data"]
    balance_data = balances["data"] if balances else {}
    pnl_data = pnl["data"] if pnl else {}
    errors = source_errors or {}
    return {
        "status": "partial" if errors else "ready",
        "confidence": "limited" if errors else "high",
        "user_id": user["user_id"],
        "account_status": user["account_status"],
        "kyc_level": user["kyc_level"],
        "operations": user["operations"],
        "orders": user["orders"],
        "portfolio": {
            "available": balances is not None,
            "asset_count": len(balance_data.get("items", [])) if balances else None,
            "portfolio_value_irt": balance_data.get("portfolio_value_irt"),
        },
        "activity_counts": {
            "trades": len(trades["data"].get("items", [])) if trades else None,
            "deposits": len(deposits["data"].get("items", [])) if deposits else None,
            "withdrawals": len(withdrawals["data"].get("items", [])) if withdrawals else None,
        },
        "pnl": {
            "available": pnl is not None,
            "calculation_complete": pnl_data.get("calculation_complete", False) if pnl else None,
            "incomplete_reason": pnl_data.get("incomplete_reason"),
            "execution_pnl": pnl_data.get("execution_pnl"),
        },
        "source_errors": errors,
        "sensitive_records_exposed": False,
        "limitations": [
            "Transaction rows, addresses, hashes, and per-asset balances are minimized from this response.",
            "Execution PnL is not complete PnL until the weighted-average ledger is connected.",
            *(["One or more exchange dependencies were unavailable; conclusions are partial."] if errors else []),
        ],
        "action_executed": False,
    }
