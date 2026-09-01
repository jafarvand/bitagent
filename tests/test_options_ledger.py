import pytest

from app.trading_options.ledger import PaperPortfolioLedger
from app.trading_options.models import OptionInstrument
from app.trading_options.snapshots import MarketSnapshot


def test_long_position_mark_to_market_and_close():
    ledger = PaperPortfolioLedger(starting_cash=10_000.0)
    ledger.apply_fill(symbol="BTC-CALL", quantity=2.0, price=100.0, fee=2.0)
    ledger.mark("BTC-CALL", 120.0)

    snap = ledger.snapshot()
    assert snap.cash == pytest.approx(9798.0)
    assert snap.unrealized_pnl == pytest.approx(40.0)
    assert snap.equity == pytest.approx(10038.0)

    ledger.apply_fill(symbol="BTC-CALL", quantity=-2.0, price=120.0, fee=2.0)
    closed = ledger.snapshot()
    assert closed.unrealized_pnl == pytest.approx(0.0)
    assert closed.realized_pnl == pytest.approx(36.0)
    assert closed.equity == pytest.approx(10036.0)


def test_snapshot_prefers_mark_and_falls_back_to_mid():
    instruments = [
        OptionInstrument(
            symbol="BTC-1",
            underlying="BTC",
            option_type="call",
            strike=100_000.0,
            expiry_ts=1,
            bid=10.0,
            ask=14.0,
            mark=None,
        ),
        OptionInstrument(
            symbol="BTC-2",
            underlying="BTC",
            option_type="put",
            strike=90_000.0,
            expiry_ts=1,
            bid=8.0,
            ask=12.0,
            mark=11.0,
        ),
    ]
    snapshot = MarketSnapshot.now(asset="BTC", instruments=instruments, index_price=95_000.0)
    assert snapshot.marks() == {"BTC-1": 12.0, "BTC-2": 11.0}
