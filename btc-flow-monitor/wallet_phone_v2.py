"""Read-only phone dashboard for the V2 BTC/ETH PAPER ledger."""
import copy
import threading
import time
from pathlib import Path

from phone_share import PhoneShare
from wallet_phone import local_portal


class V2WalletView:
    def __init__(self):
        self.lock = threading.Lock()
        self.ledger = None
        self.revision = 0
        self.ledger_version = None
        self.source_identity = None
        self.state = {}

    def update(self, ledger, connected, pending, ledger_version=None):
        with self.lock:
            # The 500ms heartbeat must not copy or publish an unchanged ledger.
            changed = (
                self.ledger is None or
                (ledger_version is not None and ledger_version != self.ledger_version) or
                (ledger_version is None and ledger is not self.source_identity)
            )
            if changed:
                self.ledger = copy.deepcopy(ledger)
                self.ledger_version = ledger_version
                self.source_identity = ledger
                self.revision += 1
            self.state = {
                "heartbeat_ms": int(time.time() * 1000),
                "connected": bool(connected),
                "pending": int(pending),
                "revision": self.revision,
            }

    def read(self):
        with self.lock:
            if self.ledger is None:
                return {
                    "schema_version": 2, "paper_only": True,
                    "real_trading_enabled": False, "wallets": {}, "totals": {},
                    "pc_live": dict(self.state),
                }
            result = copy.deepcopy(self.ledger)
            result["pc_live"] = dict(self.state)
            return result

    def read_since(self, revision):
        with self.lock:
            if str(revision) == str(self.revision):
                return {
                    "paper_only": True, "real_trading_enabled": False,
                    "unchanged": True, "pc_live": dict(self.state),
                }
        return self.read()


class WalletPhoneV2:
    def __init__(self, root, directory):
        self.view = V2WalletView()
        self.dashboard = Path(root) / "dashboard-v2.html"
        html = self.dashboard.read_text(encoding="utf-8")
        self.share = PhoneShare(self.view, directory, dashboard_html=html)
        self.share.direct_dashboard = False  # Open Home with authenticated V2 PC API
        self.portal = local_portal(self.view, self.share, self.dashboard, settings=None)
        self.url = f"http://127.0.0.1:{self.portal.server_port}/"

    def start(self):
        self.share.start()
        print("V2 PC DASHBOARD:", self.url, "Scan QR to open BTC+ETH PAPER view.", flush=True)
        import webbrowser
        webbrowser.open(self.url)

    def close(self):
        self.share.close()
        self.portal.shutdown()
        self.portal.server_close()
