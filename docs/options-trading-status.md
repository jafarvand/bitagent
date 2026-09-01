# Options trading implementation status

## Implemented

- Aevo public REST connector (testnet/mainnet selectable)
- BTC option discovery and CALL/PUT parsing
- Deterministic risk gate with confidence, daily-loss, drawdown and open-position limits
- Paper execution simulator with fee/slippage
- Paper portfolio ledger with realized/unrealized PnL and mark-to-market
- Market snapshot primitives
- Standalone FastAPI options-paper service
- API routes for markets, portfolio, PnL, paper orders and marking
- Deterministic baseline CALL/PUT/NO_TRADE model
- Directional backtest engine with win rate, profit factor, max drawdown, Sharpe and expectancy
- Aevo JSONL snapshot collector
- Unit/API tests
- CI secret-scan authentication fix

## Run locally

```bash
python -m pip install -r requirements.txt
python -m pytest -q
uvicorn app.trading_options.app:app --host 0.0.0.0 --port 9001
```

Then:

```bash
curl http://127.0.0.1:9001/health
curl 'http://127.0.0.1:9001/api/v0/options/markets?asset=BTC'
curl http://127.0.0.1:9001/api/v0/options/portfolio
```

Collect a testnet snapshot:

```bash
python scripts/options_snapshot.py --asset BTC --env testnet
```

## Safety state

Live execution is intentionally disabled. No wallet private key, signing key, API secret, withdrawal flow, or mainnet order submission is implemented in this branch.

## Remaining gates before authenticated Testnet execution

1. Mount `app.trading_options.api.router` into the main bitAgent app after review of the large existing `app/main.py` integration surface.
2. Add durable PostgreSQL/Timescale persistence for snapshots, fills and positions.
3. Validate Aevo testnet response schemas against a real snapshot and add contract fixtures.
4. Add authenticated Aevo testnet account/portfolio reads.
5. Add EIP-712 order signing in an isolated signer component; never log or persist signing secrets.
6. Add paper-vs-testnet execution reconciliation and idempotency keys.
7. Add kill switch, max notional and per-symbol exposure limits.
8. Run at least 2-4 weeks paper/shadow evaluation before enabling any live-capital path.

## M2 data/model work

Historical snapshots should be converted into time-aligned training rows. The learned model must beat the deterministic baseline on untouched walk-forward periods after fees/slippage. Candidate learned baseline: XGBoost. RL is deferred until an out-of-sample edge and stable execution/risk layer are demonstrated.
