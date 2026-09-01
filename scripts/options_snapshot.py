from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from app.trading_options.connectors.aevo import AevoConfig, AevoPublicClient


async def collect(asset: str, env: str, output: Path) -> int:
    client = AevoPublicClient(AevoConfig(env=env))
    try:
        index = await client.get_index(asset)
        options = await client.list_options(asset)
    finally:
        await client.aclose()

    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "env": env,
        "asset": asset.upper(),
        "index": index,
        "options": [asdict(option) for option in options],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, separators=(",", ":")) + "\n")
    return len(options)


def main() -> None:
    parser = argparse.ArgumentParser(description="Append one Aevo options market snapshot to JSONL")
    parser.add_argument("--asset", default="BTC")
    parser.add_argument("--env", choices=("testnet", "mainnet"), default="testnet")
    parser.add_argument("--output", default="data/options/aevo_snapshots.jsonl")
    args = parser.parse_args()
    count = asyncio.run(collect(args.asset, args.env, Path(args.output)))
    print(f"saved {count} {args.asset.upper()} options to {args.output}")


if __name__ == "__main__":
    main()
