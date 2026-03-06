"""
curve_alert.py
──────────────
Real-time Curve 3Pool monitoring + depeg alert system.

Unlike monitor_curve.py which queries state once, this module runs a polling
loop and emits alerts when pool composition crosses configured thresholds.

Alert levels:
  WATCH   : token share > 40% (watch zone)
  WARNING : token share > 50% (leading signal)
  ALERT   : token share > 65% (depeg in progress)
  CRITICAL: token share > 75% (historical threshold — act immediately)

Usage:
  python -m src.curve_alert
  python -m src.curve_alert --interval 60 --threshold 50
"""

import os
import time
import argparse
import logging
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional

from web3 import Web3
from dotenv import load_dotenv

load_dotenv()

# ── Configuration ─────────────────────────────────────────────────────────────

RPC_URL   = os.getenv("ETH_RPC_URL", "https://eth-mainnet.g.alchemy.com/v2/<YOUR_API_KEY>")
POOL_ADDR = "0xbEbc44782C7dB0a1A60Cb6fe97d0b483032FF1C7"  # Curve 3Pool

# Alert thresholds (%)
THRESHOLDS = {
    "WATCH":    40.0,
    "WARNING":  50.0,
    "ALERT":    65.0,
    "CRITICAL": 75.0,
}

# Swap size used for slippage measurement ($1M)
DEFAULT_SWAP_SIZE = 1_000_000

ABI = [
    {
        "name": "balances",
        "inputs": [{"name": "i", "type": "uint256"}],
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "name": "get_virtual_price",
        "inputs": [],
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "name": "get_dy",
        "inputs": [
            {"name": "i", "type": "int128"},
            {"name": "j", "type": "int128"},
            {"name": "dx", "type": "uint256"},
        ],
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "name": "A",
        "inputs": [],
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
]

# ── Logging setup ─────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("curve_alert")


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class PoolSnapshot:
    """3Pool state at a single point in time."""
    timestamp:        datetime
    dai_pct:          float
    usdc_pct:         float
    usdt_pct:         float
    virtual_price:    float
    amp:              int
    price_impact_pct: float   # $1M USDT→USDC slippage

    @property
    def max_token(self) -> tuple[str, float]:
        """Return the token with the highest share and its percentage."""
        composition = {
            "DAI":  self.dai_pct,
            "USDC": self.usdc_pct,
            "USDT": self.usdt_pct,
        }
        token = max(composition, key=composition.__getitem__)
        return token, composition[token]

    @property
    def alert_level(self) -> Optional[str]:
        """Current alert level. Returns None if all metrics are normal."""
        _, pct = self.max_token
        for level in ("CRITICAL", "ALERT", "WARNING", "WATCH"):
            if pct >= THRESHOLDS[level]:
                return level
        return None

    def is_stressed(self) -> bool:
        return self.alert_level is not None


@dataclass
class AlertEvent:
    """Record of a fired alert."""
    level:     str
    token:     str
    pct:       float
    snapshot:  PoolSnapshot
    message:   str


# ── On-chain query ────────────────────────────────────────────────────────────

def fetch_snapshot(
    pool,
    swap_size: float = DEFAULT_SWAP_SIZE,
) -> PoolSnapshot:
    """
    Read current Curve 3Pool state on-chain and return as PoolSnapshot.

    Parameters
    ----------
    pool      : web3 contract instance
    swap_size : swap size used for slippage measurement (USD)
    """
    dai  = pool.functions.balances(0).call() / 1e18   # DAI  18 decimals
    usdc = pool.functions.balances(1).call() / 1e6    # USDC  6 decimals
    usdt = pool.functions.balances(2).call() / 1e6    # USDT  6 decimals
    total = dai + usdc + usdt

    virtual_price = pool.functions.get_virtual_price().call() / 1e18
    amp           = pool.functions.A().call()

    # Measure $1M USDT → USDC slippage (i=2:USDT, j=1:USDC)
    dx  = int(swap_size * 1e6)
    dy  = pool.functions.get_dy(2, 1, dx).call() / 1e6
    price_impact = (swap_size - dy) / swap_size * 100

    return PoolSnapshot(
        timestamp        = datetime.now(timezone.utc),
        dai_pct          = dai  / total * 100,
        usdc_pct         = usdc / total * 100,
        usdt_pct         = usdt / total * 100,
        virtual_price    = virtual_price,
        amp              = amp,
        price_impact_pct = price_impact,
    )


# ── Alert evaluation + output ─────────────────────────────────────────────────

def evaluate_and_alert(
    snapshot:  PoolSnapshot,
    prev:      Optional[PoolSnapshot] = None,
) -> Optional[AlertEvent]:
    """
    Evaluate the current snapshot and return an AlertEvent if warranted.
    Only fires when the alert level escalates from the previous snapshot
    (CRITICAL always fires).

    Returns
    -------
    AlertEvent if alert fired, else None
    """
    level = snapshot.alert_level
    if level is None:
        return None

    # Suppress repeated alerts at the same level (except CRITICAL)
    if prev is not None and prev.alert_level == level and level != "CRITICAL":
        return None

    token, pct = snapshot.max_token

    msg_map = {
        "WATCH":    f"[WATCH]    {token} {pct:.1f}% — entering watch zone",
        "WARNING":  f"[WARNING]  {token} {pct:.1f}% — depeg leading signal (1.5x normal 33.3%)",
        "ALERT":    f"[ALERT]    {token} {pct:.1f}% — depeg in progress (consider Strategy ②)",
        "CRITICAL": f"[CRITICAL] {token} {pct:.1f}% — historical threshold breached (act now)",
    }

    event = AlertEvent(
        level    = level,
        token    = token,
        pct      = pct,
        snapshot = snapshot,
        message  = msg_map[level],
    )

    _print_alert(event)
    return event


def _print_alert(event: AlertEvent) -> None:
    """Print alert to console."""
    snap = event.snapshot
    sep  = "=" * 60

    print(sep)
    print(f"  {event.message}")
    print(f"  Time:        {snap.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"  Composition: DAI {snap.dai_pct:.1f}%  USDC {snap.usdc_pct:.1f}%  USDT {snap.usdt_pct:.1f}%")
    print(f"  Virtual Price: {snap.virtual_price:.6f}   A: {snap.amp}")
    print(f"  $1M slippage:  {snap.price_impact_pct:.4f}%")

    # Strategy hints
    if event.level in ("ALERT", "CRITICAL"):
        if event.token == "USDT":
            print()
            print("  [Strategy hint] USDT oversupply → consider borrowing USDT on Aave and swapping to USDC")
            print("                  See backtest_historical.py Strategy ②")
        elif event.token == "USDC":
            print()
            print("  [Strategy hint] USDC scarce → check premium on USDT→USDC swap")
            print("                  See backtest_historical.py Strategy ①")

    print(sep)


# ── Polling loop ──────────────────────────────────────────────────────────────

def run_monitor(
    interval:  int   = 120,    # polling interval in seconds
    threshold: float = 40.0,   # minimum threshold to print details (below = log only)
    swap_size: float = DEFAULT_SWAP_SIZE,
    max_rounds: Optional[int] = None,  # max iterations (for testing)
) -> None:
    """
    Curve 3Pool polling loop.

    Parameters
    ----------
    interval   : seconds between on-chain queries. Alchemy free plan allows 300 req/min
    threshold  : pool share below this → log only, no detailed output
    swap_size  : swap size for slippage measurement (USD)
    max_rounds : if set, stop after this many iterations (prevents infinite loop in tests)
    """
    w3   = Web3(Web3.HTTPProvider(RPC_URL))
    pool = w3.eth.contract(
        address=Web3.to_checksum_address(POOL_ADDR), abi=ABI
    )

    logger.info("Curve 3Pool monitoring started")
    logger.info(f"  Polling interval: {interval}s  |  Alert threshold: {threshold}%")
    logger.info(f"  Pool address: {POOL_ADDR}")

    prev_snapshot: Optional[PoolSnapshot] = None
    alert_history: list[AlertEvent]       = []
    rounds = 0

    while True:
        try:
            snapshot = fetch_snapshot(pool, swap_size)
            token, pct = snapshot.max_token

            # Detailed output above threshold, single-line log below
            if pct >= threshold:
                event = evaluate_and_alert(snapshot, prev_snapshot)
                if event:
                    alert_history.append(event)
            else:
                logger.info(
                    f"[OK] {token} {pct:.1f}%  VP={snapshot.virtual_price:.5f}"
                    f"  slippage={snapshot.price_impact_pct:.4f}%"
                )

            prev_snapshot = snapshot

        except Exception as exc:
            logger.error(f"Query error: {exc}")

        rounds += 1
        if max_rounds is not None and rounds >= max_rounds:
            break

        time.sleep(interval)

    logger.info(f"Monitoring stopped. Total alerts: {len(alert_history)}")
    return alert_history


# ── CLI entry point ───────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Curve 3Pool real-time depeg alert system"
    )
    parser.add_argument(
        "--interval", type=int, default=120,
        help="Polling interval in seconds (default 120)"
    )
    parser.add_argument(
        "--threshold", type=float, default=40.0,
        help="Output threshold %% (default 40.0)"
    )
    parser.add_argument(
        "--swap-size", type=float, default=DEFAULT_SWAP_SIZE,
        help="Slippage measurement swap size in USD (default 1,000,000)"
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    run_monitor(
        interval  = args.interval,
        threshold = args.threshold,
        swap_size = args.swap_size,
    )
