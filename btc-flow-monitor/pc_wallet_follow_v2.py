"""Real-time BTC/ETH PAPER observer with durable per-asset pending queue."""
from __future__ import annotations
import asyncio
import datetime as dt
import json
import sqlite3
import sys
import time
from pathlib import Path

from websockets.asyncio.client import connect

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "pending-paper-v2.sqlite3"
OUT = ROOT / "trader-discovery" / "wallet-paper-v2.json"
ENGINE_VERSION = "cash-flow-v2-paper-20261121-1"


def load_ledger():
    data = json.loads(OUT.read_text(encoding="utf-8"))
    if data.get("paper_only") is not True or data.get("real_trading_enabled") is not False:
        raise ValueError("PAPER_ONLY invariant violated")
    return data


def save_ledger(data):
    from wallet_paper_v2 import save_atomic
    save_atomic(data)


class V2Observer:
    def __init__(self, db):
        self.db = db
        self.ledger = load_ledger()
        self.lock = asyncio.Lock()
        self.connected = False
        self.received = 0
        self.applied = 0
        self.errors = 0
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS pending_v2 (
                seq INTEGER PRIMARY KEY,
                wallet TEXT NOT NULL,
                coin TEXT NOT NULL,
                tid TEXT NOT NULL,
                fill_time INTEGER NOT NULL,
                payload TEXT NOT NULL,
                received_ms INTEGER NOT NULL,
                UNIQUE(wallet, coin, tid)
            )
        """)
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_pending_v2_asset ON pending_v2(wallet,coin,fill_time,seq)")
        self.db.commit()

    def receive(self, message):
        data = message.get("data")
        if message.get("channel") != "userFills" or not isinstance(data, dict):
            return
        wallet = str(data.get("user", "")).lower()
        if wallet not in self.ledger["wallets"]:
            return
        received_ms = int(time.time() * 1000)
        rows = [r for r in data.get("fills", []) if r.get("coin") in ("BTC", "ETH")]
        with self.db:
            for row in rows:
                coin = row["coin"]
                self.db.execute(
                    "INSERT OR IGNORE INTO pending_v2(wallet,coin,tid,fill_time,payload,received_ms) VALUES(?,?,?,?,?,?)",
                    (wallet, coin, str(row["tid"]), int(row["time"]), json.dumps(row), received_ms)
                )
        self.received += len(rows)

    def drain_asset(self, wallet, coin):
        account = self.ledger["wallets"][wallet][coin]
        rows = self.db.execute(
            "SELECT seq,payload,received_ms FROM pending_v2 WHERE wallet=? AND coin=? ORDER BY fill_time,seq",
            (wallet, coin)
        ).fetchall()
        if not rows:
            return
        changed = False
        for seq, payload, received_ms in rows:
            row = json.loads(payload)
            ms, tid = int(row["time"]), int(row["tid"])
            key = [ms, tid]
            if ms < int(account.get("fill_cursor", 0)) or key in account.get("stream_keys", []):
                self.db.execute("DELETE FROM pending_v2 WHERE seq=?", (seq,))
                continue
            before = float(row["startPosition"])
            if abs(before - float(account.get("source_size", 0.0))) > 1e-8:
                break
            from cash_flow_v2_core import apply_wallet_fill, mark_account
            now_ms = int(time.time() * 1000)
            status = apply_wallet_fill(
                self.ledger, wallet, row,
                float(account.get("source_equity_usd") or 0.0),
                allow_open=(-2000 <= now_ms - ms <= 15000)
            )
            if status == "applied":
                account = self.ledger["wallets"][wallet][coin]
                stamp = dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).isoformat()
                mark_account(account, float(row["px"]), stamp)
                account["last_fill"]["received_at"] = dt.datetime.fromtimestamp(received_ms/1000,dt.timezone.utc).isoformat()
                account["last_fill"]["receive_delay_ms"] = received_ms - ms
                account["last_fill"]["apply_delay_ms"] = now_ms - ms
                account["error"] = None
                self.db.execute("DELETE FROM pending_v2 WHERE seq=?", (seq,))
                self.applied += 1
                changed = True
            else:
                self.db.execute("DELETE FROM pending_v2 WHERE seq=?", (seq,))
        self.db.commit()
        if changed:
            save_ledger(self.ledger)

    async def handle(self, message):
        self.receive(message)
        data = message.get("data")
        if not isinstance(data, dict):
            return
        wallet = str(data.get("user", "")).lower()
        if wallet not in self.ledger["wallets"]:
            return
        async with self.lock:
            for coin in ("BTC", "ETH"):
                self.drain_asset(wallet, coin)

    async def reconcile_loop(self):
        from wallet_paper_v2 import main as reconcile
        while True:
            await asyncio.sleep(60)
            async with self.lock:
                try:
                    try:
                        await asyncio.to_thread(reconcile)
                    except SystemExit as exit_error:
                        if exit_error.code not in (0, 2):
                            raise
                    self.ledger = load_ledger()
                    for wallet in self.ledger["wallets"]:
                        for coin in ("BTC", "ETH"):
                            self.drain_asset(wallet, coin)
                    print("V2_RECONCILE_OK", flush=True)
                except Exception as exc:
                    self.errors += 1
                    print("V2_RECONCILE_ERROR", str(exc)[:300], flush=True)

    async def listen(self):
        while True:
            try:
                async with connect("wss://api.hyperliquid.xyz/ws", open_timeout=10, ping_interval=20) as ws:
                    self.connected = True
                    for wallet in self.ledger["wallets"]:
                        await ws.send(json.dumps({
                            "method": "subscribe",
                            "subscription": {"type": "userFills", "user": wallet}
                        }))
                    print("V2_WS_CONNECTED", len(self.ledger["wallets"]), "wallets; BTC+ETH; PAPER ONLY", flush=True)
                    async for raw in ws:
                        try:
                            await self.handle(json.loads(raw))
                        except (ValueError, KeyError, TypeError) as exc:
                            self.errors += 1
                            print("V2_EVENT_HOLD", str(exc)[:200], flush=True)
            except Exception as exc:
                self.connected = False
                print("V2_WS_RECONNECT", str(exc)[:240], flush=True)
                await asyncio.sleep(3)
            finally:
                self.connected = False


async def run():
    from wallet_paper_v2 import main as reconcile
    from wallet_phone_v2 import WalletPhoneV2
    stop_file = ROOT / "STOP_CASH_FLOW_V2"
    stop_event = asyncio.Event()

    async def watch_stop():
        while not stop_file.exists():
            await asyncio.sleep(1)
        stop_event.set()

    stop_task = asyncio.create_task(watch_stop())
    phone = None
    try:
        try:
            await asyncio.to_thread(reconcile)
        except SystemExit as exc:
            if exc.code not in (0, 2):
                raise
        if stop_event.is_set():
            return
        with sqlite3.connect(DB_PATH) as db:
            observer = V2Observer(db)
            phone = WalletPhoneV2(ROOT, ROOT)
            phone.view.update(observer.ledger, observer.connected,
                              db.execute("SELECT COUNT(*) FROM pending_v2").fetchone()[0])
            phone.start()

            async def update_phone():
                while True:
                    pending = db.execute("SELECT COUNT(*) FROM pending_v2").fetchone()[0]
                    phone.view.update(observer.ledger, observer.connected, pending)
                    await asyncio.sleep(0.5)

            print("ENGINE", ENGINE_VERSION, "PAPER_ONLY", flush=True)
            workers = [
                asyncio.create_task(observer.listen()),
                asyncio.create_task(observer.reconcile_loop()),
                asyncio.create_task(update_phone()),
            ]
            done, pending = await asyncio.wait(
                workers + [stop_task], return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                if task is not stop_task:
                    task.result()
    finally:
        stop_task.cancel()
        await asyncio.gather(stop_task, return_exceptions=True)
        if phone is not None:
            await asyncio.to_thread(phone.close)
        if stop_file.exists():
            stop_file.unlink()
        print("V2_ENGINE_STOPPED_GRACEFULLY", flush=True)


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    asyncio.run(run())
