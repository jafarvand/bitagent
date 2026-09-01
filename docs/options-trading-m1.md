# Options Trading — Milestone M1

Status: scaffold started on `feature/options-trading-m1`.

## Goal

Build a testnet/paper-trading skeleton for a crypto options agent with this flow:

`Market Data -> Features -> Signal -> Risk Gate -> Testnet Execution -> PnL`

## M1 scope

- Exchange adapter interface
- BTC options instrument discovery
- Call/Put market snapshots
- Order-book reads
- Storage-ready market-data records
- Dummy `CALL` / `PUT` / `NO_TRADE` signal generation
- Independent hard risk gate
- Testnet-only execution path
- Trade/PnL audit records
- Unit tests

## Safety defaults

- No mainnet execution in M1
- No withdrawal capability
- No model permission to modify risk limits
- Default minimum signal confidence: 0.65
- Default max trade allocation: 1% of portfolio
- Default max daily loss: 3%
- Default max drawdown: 10%
- Default max open positions: 5

These limits are starter engineering defaults, not a claim that they are optimal for live trading.

## Planned module layout

```text
app/trading_options/
  __init__.py
  models.py
  risk.py
  connectors/
    base.py
    aevo.py
  signals/
    baseline.py
  execution/
    paper.py
  pnl.py
```

## Next implementation step

1. Define the exchange adapter contract.
2. Implement the Aevo testnet connector only after validating current official API authentication and endpoint schemas.
3. Add paper execution and unit tests.
4. Add historical data capture and a backtest harness.
5. Add XGBoost baseline before any RL model.
