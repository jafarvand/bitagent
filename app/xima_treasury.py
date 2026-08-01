from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class AssetPosition(BaseModel):
    asset: str = Field(pattern=r"^[A-Z0-9]{2,20}$")
    controlled_assets: Decimal = Field(ge=0)
    customer_liabilities: Decimal = Field(ge=0)
    valuation_price: Decimal = Field(gt=0)


class WalletPosition(BaseModel):
    wallet_group: str = Field(min_length=2, max_length=100)
    asset: str = Field(pattern=r"^[A-Z0-9]{2,20}$")
    custody_tier: Literal["hot", "warm", "cold", "custodian"]
    available: Decimal = Field(ge=0)
    minimum_operational: Decimal = Field(ge=0)
    maximum_operational: Decimal = Field(gt=0)
    connected: bool


class Obligation(BaseModel):
    obligation_id: str = Field(min_length=2, max_length=100)
    asset: str = Field(pattern=r"^[A-Z0-9]{2,20}$")
    amount: Decimal = Field(gt=0)
    due_at: datetime
    status: Literal["open", "in_progress", "resolved"]
    owner: str = Field(min_length=2, max_length=100)


class ReconciliationPosition(BaseModel):
    asset: str = Field(pattern=r"^[A-Z0-9]{2,20}$")
    ledger_amount: Decimal = Field(ge=0)
    wallet_amount: Decimal = Field(ge=0)
    external_amount: Decimal = Field(ge=0)
    tolerance: Decimal = Field(ge=0)
    source_complete: bool


class TreasuryAnalysisRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=100)
    observed_at: datetime
    evidence_refs: list[str] = Field(min_length=1, max_length=100)
    owner: str = Field(min_length=2, max_length=100)
    evidence_fresh: bool
    conflicting_fields: list[str] = Field(default_factory=list, max_length=100)
    positions: list[AssetPosition] = Field(min_length=1, max_length=500)
    wallets: list[WalletPosition] = Field(default_factory=list, max_length=1000)
    obligations: list[Obligation] = Field(default_factory=list, max_length=1000)
    reconciliation: list[ReconciliationPosition] = Field(min_length=1, max_length=500)


def _money(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.00000001")))


def _percent(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01")))


def analyze_treasury(request: TreasuryAnalysisRequest) -> dict:
    now = datetime.now(UTC)
    common = {
        "tenant_id": request.tenant_id, "observed_at": request.observed_at.isoformat(),
        "analyzed_at": now.isoformat(), "evidence_refs": request.evidence_refs,
        "owner": request.owner, "action_executed": False,
    }
    if not request.evidence_fresh or request.conflicting_fields:
        return {
            **common, "status": "blocked", "severity": "unknown", "confidence": "none",
            "positions": [], "wallet_exceptions": [], "reconciliation_exceptions": [],
            "limitations": (
                (["stale evidence"] if not request.evidence_fresh else []) +
                ([f"conflicting fields: {', '.join(request.conflicting_fields)}"]
                 if request.conflicting_fields else [])
            ),
            "recommended_next_action": "Refresh and reconcile financial evidence before review.",
        }

    positions = []
    for item in request.positions:
        difference = item.controlled_assets - item.customer_liabilities
        coverage = (
            item.controlled_assets / item.customer_liabilities * 100
            if item.customer_liabilities else Decimal("100")
        )
        positions.append({
            "asset": item.asset, "controlled_assets": _money(item.controlled_assets),
            "customer_liabilities": _money(item.customer_liabilities),
            "difference": _money(difference), "coverage_percent": _percent(coverage),
            "valuation_price": _money(item.valuation_price),
            "deficit": difference < 0,
        })
    wallet_exceptions = []
    for wallet in request.wallets:
        reason = None
        if not wallet.connected:
            reason = "wallet_disconnected"
        elif wallet.available < wallet.minimum_operational:
            reason = "below_minimum"
        elif wallet.available > wallet.maximum_operational:
            reason = "above_maximum"
        if reason:
            wallet_exceptions.append({
                "wallet_group": wallet.wallet_group, "asset": wallet.asset,
                "custody_tier": wallet.custody_tier, "reason": reason,
                "available": _money(wallet.available),
                "minimum": _money(wallet.minimum_operational),
                "maximum": _money(wallet.maximum_operational),
            })
    reconciliation = []
    reconciliation_exceptions = []
    for item in request.reconciliation:
        difference = item.wallet_amount + item.external_amount - item.ledger_amount
        result = {
            "asset": item.asset, "ledger_amount": _money(item.ledger_amount),
            "wallet_amount": _money(item.wallet_amount),
            "external_amount": _money(item.external_amount),
            "difference": _money(difference), "absolute_difference": _money(abs(difference)),
            "tolerance": _money(item.tolerance), "source_complete": item.source_complete,
            "within_tolerance": item.source_complete and abs(difference) <= item.tolerance,
        }
        reconciliation.append(result)
        if not result["within_tolerance"]:
            reconciliation_exceptions.append(result)
    obligations = []
    for item in request.obligations:
        due = item.due_at.astimezone(UTC)
        overdue_seconds = max(0, int((now - due).total_seconds())) if item.status != "resolved" else 0
        obligations.append({
            **item.model_dump(mode="json"), "due_at": due.isoformat(),
            "overdue": overdue_seconds > 0, "overdue_seconds": overdue_seconds,
        })
    deficits = [item for item in positions if item["deficit"]]
    overdue = [item for item in obligations if item["overdue"]]
    critical = bool(deficits or any(not item["source_complete"] for item in reconciliation_exceptions))
    warning = bool(wallet_exceptions or reconciliation_exceptions or overdue)
    severity = "critical" if critical else "warning" if warning else "healthy"
    total_assets_value = sum(
        item.controlled_assets * item.valuation_price for item in request.positions
    )
    total_liabilities_value = sum(
        item.customer_liabilities * item.valuation_price for item in request.positions
    )
    return {
        **common, "status": "ready", "severity": severity, "confidence": "high",
        "positions": positions,
        "valuation": {
            "controlled_assets": _money(total_assets_value),
            "customer_liabilities": _money(total_liabilities_value),
            "difference": _money(total_assets_value - total_liabilities_value),
            "boundary": "Uses submitted valuation prices; not audited financial statements.",
        },
        "wallet_exceptions": wallet_exceptions, "obligations": obligations,
        "reconciliation": reconciliation,
        "reconciliation_exceptions": reconciliation_exceptions,
        "treasury_brief": {
            "headline": f"Treasury evidence is {severity}.",
            "deficit_assets": [item["asset"] for item in deficits],
            "wallet_exception_count": len(wallet_exceptions),
            "reconciliation_exception_count": len(reconciliation_exceptions),
            "overdue_obligation_count": len(overdue),
        },
        "limitations": ["No funds moved and no ledger or wallet state changed."],
        "recommended_next_action": (
            "Escalate deficits or incomplete reconciliation sources immediately."
            if critical else "Assign and investigate treasury exceptions." if warning else
            "Continue daily reconciliation monitoring."
        ),
    }
