from pathlib import Path

from app.trading_options.ledger import PaperPortfolioLedger
from app.trading_options.models import TradeAction
from app.trading_options.paper import PaperFill
from app.trading_options.persistence import OptionsAuditStore


def test_audit_store_records_fill_and_snapshot(tmp_path: Path):
    store = OptionsAuditStore(tmp_path / "audit.sqlite3")
    fill = PaperFill(
        fill_id="fill-1",
        timestamp="2026-09-01T00:00:00+00:00",
        symbol="BTC-TEST-C",
        action=TradeAction.CALL,
        quantity=1.0,
        price=100.0,
        notional=100.0,
        fee=0.05,
        reason="test",
    )
    store.record_fill(fill)
    fills = store.recent_fills()
    assert fills[0]["fill_id"] == "fill-1"
    assert fills[0]["action"] == "CALL"

    ledger = PaperPortfolioLedger(starting_cash=1000.0)
    ledger.apply_fill(symbol="BTC-TEST-C", quantity=1.0, price=100.0, fee=0.05)
    ledger.mark("BTC-TEST-C", 110.0)
    store.record_snapshot(ledger.snapshot())
    snapshots = store.recent_snapshots()
    assert snapshots[0]["equity"] == 1009.95
    assert snapshots[0]["positions"][0]["symbol"] == "BTC-TEST-C"
