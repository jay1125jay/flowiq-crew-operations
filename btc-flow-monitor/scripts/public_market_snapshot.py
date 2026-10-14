#!/usr/bin/env python3
"""Public market snapshot for PAPER research. No credentials, orders, or private data."""
import datetime as dt
import json
import pathlib
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "public-market.json"
API = "https://api.hyperliquid.xyz/info"

def fetch(payload):
    req = urllib.request.Request(
        API, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "BTC-Flow-Paper-Research/1.0"},
        method="POST")
    with urllib.request.urlopen(req, timeout=20) as res:
        return json.load(res)

def main():
    mids = fetch({"type": "allMids"})
    btc = float(mids["BTC"])
    if not 1000 <= btc <= 1000000:
        raise ValueError("BTC price outside validation bounds")
    snapshot = {
        "schema_version": 1,
        "source": "hyperliquid_public_api",
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "btc_mid_usd": btc,
        "paper_only": True,
        "orders_enabled": False,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Snapshot validated; price:", btc)

if __name__ == "__main__":
    main()
