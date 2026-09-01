from app.trading_options.backtest import BacktestBar, label_direction, run_backtest
from app.trading_options.models import TradeAction, TradingSignal
from app.trading_options.signals import BaselineSignalModel, FeatureVector


def test_label_direction_call_put_no_trade():
    assert label_direction(100.0, 101.0, 0.008) == TradeAction.CALL
    assert label_direction(100.0, 99.0, 0.008) == TradeAction.PUT
    assert label_direction(100.0, 100.2, 0.008) == TradeAction.NO_TRADE


def test_backtest_metrics_are_computed():
    bars = [
        BacktestBar(ts=1, price=100.0, future_price=102.0),
        BacktestBar(ts=2, price=100.0, future_price=98.0),
        BacktestBar(ts=3, price=100.0, future_price=99.0),
    ]
    signals = [
        TradingSignal(TradeAction.CALL, 0.8),
        TradingSignal(TradeAction.PUT, 0.8),
        TradingSignal(TradeAction.CALL, 0.8),
    ]
    result = run_backtest(bars, signals, fee_fraction=0.0)
    assert len(result.trades) == 3
    assert result.win_rate == 2 / 3
    assert result.total_return > 0
    assert result.max_drawdown > 0
    assert result.expectancy > 0


def test_baseline_can_call_put_and_abstain():
    model = BaselineSignalModel(trade_threshold=0.1)
    bullish = model.predict(FeatureVector(momentum_5m=0.02, momentum_1h=0.04, rsi=68, orderbook_imbalance=0.7))
    bearish = model.predict(FeatureVector(momentum_5m=-0.02, momentum_1h=-0.04, rsi=32, orderbook_imbalance=-0.7))
    neutral = model.predict(FeatureVector())
    assert bullish.action == TradeAction.CALL
    assert bearish.action == TradeAction.PUT
    assert neutral.action == TradeAction.NO_TRADE
