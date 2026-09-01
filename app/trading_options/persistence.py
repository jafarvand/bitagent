from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Iterable

from .ledger import LedgerSnapshot
from .paper import PaperFill


class OptionsAuditStore:
    """Durable local audit store for M1/M2.

    SQLite is deliberately used here because it requires no new runtime service.
    The schema is small and can later be mirrored into PostgreSQL/TimescaleDB.
    """

    def __init__(self, path: str | Path = "data/options/options_audit.sqlite3") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS fills (
                    fill_id TEXT PRIMARY KEY,
                    ts TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    action TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    price REAL NOT NULL,
                    notional REAL NOT NULL,
                    fee REAL NOT NULL,
                    reason TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS portfolio_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    cash REAL NOT NULL,
                    realized_pnl REAL NOT NULL,
                    unrealized_pnl REAL NOT NULL,
                    equity REAL NOT NULL,
                    positions_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_fills_ts ON fills(ts);
                CREATE INDEX IF NOT EXISTS idx_fills_symbol ON fills(symbol);
                CREATE INDEX IF NOT EXISTS idx_snapshots_ts ON portfolio_snapshots(ts);
                """
            )

    def record_fill(self, fill: PaperFill) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO fills
                (fill_id, ts, symbol, action, quantity, price, notional, fee, reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    fill.fill_id,
                    fill.timestamp,
                    fill.symbol,
                    fill.action.value,
                    fill.quantity,
                    fill.price,
                    fill.notional,
                    fill.fee,
                    fill.reason,
                ),
            )

    def record_snapshot(self, snapshot: LedgerSnapshot) -> None:
        positions_json = json.dumps([asdict(position) for position in snapshot.positions], separators=(",", ":"))
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO portfolio_snapshots
                (ts, cash, realized_pnl, unrealized_pnl, equity, positions_json)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    snapshot.ts.isoformat(),
                    snapshot.cash,
                    snapshot.realized_pnl,
                    snapshot.unrealized_pnl,
                    snapshot.equity,
                    positions_json,
                ),
            )

    def recent_fills(self, limit: int = 100) -> list[dict]:
        if limit <= 0:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM fills ORDER BY ts DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def recent_snapshots(self, limit: int = 100) -> list[dict]:
        if limit <= 0:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM portfolio_snapshots ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            item["positions"] = json.loads(item.pop("positions_json"))
            results.append(item)
        return results
