"""
monitor_curve.py
────────────────
Real-time on-chain monitoring of Curve 3Pool.
- balances()          : query DAI/USDC/USDT pool share
- get_virtual_price() : query LP token virtual price
- A()                 : query amplification coefficient
- get_dy()            : measure slippage (price impact)

Usage: python -m src.monitor_curve  (activate virtual environment first)
"""

import os
from web3 import Web3
from dotenv import load_dotenv

load_dotenv()

RPC_URL   = os.getenv("ETH_RPC_URL", "https://eth-mainnet.g.alchemy.com/v2/<YOUR_API_KEY>")
POOL_ADDR = "0xbEbc44782C7dB0a1A60Cb6fe97d0b483032FF1C7"  # Curve 3Pool

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


def get_pool_state(pool_size_usd: float = 1_000_000) -> dict:
    """
    Query the current state of Curve 3Pool.

    Parameters
    ----------
    pool_size_usd : float
        Swap size used to measure slippage (USD, default $1M)

    Returns
    -------
    dict : {dai_pct, usdc_pct, usdt_pct, virtual_price, A, price_impact_pct}
    """
    w3   = Web3(Web3.HTTPProvider(RPC_URL))
    pool = w3.eth.contract(address=Web3.to_checksum_address(POOL_ADDR), abi=ABI)

    # Pool reserves (DAI=18 decimals, USDC=6 decimals, USDT=6 decimals)
    dai  = pool.functions.balances(0).call() / 1e18
    usdc = pool.functions.balances(1).call() / 1e6
    usdt = pool.functions.balances(2).call() / 1e6
    total = dai + usdc + usdt

    # LP token virtual price (healthy range ≈ 1.0~1.07)
    virtual_price = pool.functions.get_virtual_price().call() / 1e18

    # Amplification coefficient (higher = stronger 1:1 peg, currently ~2000)
    amp = pool.functions.A().call()

    # Slippage: output received for USDT → USDC swap (i=2:USDT, j=1:USDC)
    dx  = int(pool_size_usd * 1e6)  # USDT 6 decimals
    dy  = pool.functions.get_dy(2, 1, dx).call() / 1e6
    price_impact = (pool_size_usd - dy) / pool_size_usd * 100  # %

    return {
        "dai_pct":          dai  / total * 100,
        "usdc_pct":         usdc / total * 100,
        "usdt_pct":         usdt / total * 100,
        "virtual_price":    virtual_price,
        "A":                amp,
        "price_impact_pct": price_impact,
        "swap_size_usd":    pool_size_usd,
    }


def print_state(state: dict) -> None:
    """Print pool state in a human-readable format."""
    print("=" * 50)
    print("Curve 3Pool State")
    print("=" * 50)
    print(f"  DAI   share: {state['dai_pct']:6.2f}%")
    print(f"  USDC  share: {state['usdc_pct']:6.2f}%")
    print(f"  USDT  share: {state['usdt_pct']:6.2f}%")
    print(f"  Virtual Price: {state['virtual_price']:.6f}  (healthy: ~1.00~1.07)")
    print(f"  A (amplification): {state['A']}              (higher = more stable)")
    print(f"  ${state['swap_size_usd']/1e6:.0f}M USDT→USDC slippage: {state['price_impact_pct']:.4f}%")
    print()

    # Alert evaluation
    alerts = []
    if state["usdt_pct"] > 50:
        alerts.append(f"[ALERT] USDT share {state['usdt_pct']:.1f}% > 50% — depeg leading signal")
    if state["usdc_pct"] > 50:
        alerts.append(f"[ALERT] USDC share {state['usdc_pct']:.1f}% > 50% — depeg leading signal")
    if state["virtual_price"] < 1.0:
        alerts.append(f"[ALERT] Virtual Price {state['virtual_price']:.6f} < 1.0 — pool under stress")
    if state["price_impact_pct"] > 0.1:
        alerts.append(f"[WARN]  Slippage {state['price_impact_pct']:.4f}% — liquidity thinning")

    if alerts:
        for a in alerts:
            print(a)
    else:
        print("[OK] All metrics normal")


if __name__ == "__main__":
    state = get_pool_state(pool_size_usd=1_000_000)
    print_state(state)
