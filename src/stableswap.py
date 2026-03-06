"""
stableswap.py
─────────────
Curve StableSwap invariant implementation.

Unlike standard AMMs (xy=k), Curve uses a formula optimized for stablecoin swaps.
StableSwap formula: A·n^n·Σ(x_i) + D = A·D·n^n + D^(n+1) / (n^n · Π(x_i))
  - A: amplification coefficient. Higher = more stable price. 3Pool uses ~2000
  - n: number of tokens (3Pool → n=3)
  - x_i: reserve of each token
  - D: invariant (measure of total liquidity)

Core functions implemented here:
  get_D()           : compute invariant D from current reserves
  get_y()           : compute new balance of token j after token i changes to x_new
  simulate_swap()   : compute swap output for a single pool
  simulate_split()  : compute optimal output when routing across multiple pools
"""

from dataclasses import dataclass, field
from typing import Optional
import numpy as np
from scipy.optimize import minimize_scalar


# ── Pool state dataclass ──────────────────────────────────────────────────────

@dataclass
class PoolState:
    """
    Represents the state of a single Curve StableSwap pool.

    Attributes
    ----------
    name     : pool name (e.g. "Curve 3Pool", "Uniswap V3 USDC-USDT")
    tokens   : list of token symbols (e.g. ["DAI", "USDC", "USDT"])
    reserves : USD-denominated reserves in the same order as tokens
    A        : amplification coefficient. Curve 3Pool = 2000, Uniswap approx = low value
    fee      : swap fee rate (e.g. 0.0004 = 0.04%)
    """
    name:     str
    tokens:   list[str]
    reserves: list[float]
    A:        int   = 2000
    fee:      float = 0.0004  # Curve 3Pool default fee

    def __post_init__(self):
        assert len(self.tokens) == len(self.reserves), "tokens and reserves must have the same length."

    def token_index(self, symbol: str) -> int:
        """Return the index of a token by its symbol."""
        try:
            return self.tokens.index(symbol.upper())
        except ValueError:
            raise ValueError(f"Token '{symbol}' not in pool. Pool tokens: {self.tokens}")

    @property
    def total(self) -> float:
        """Total liquidity (USD)."""
        return sum(self.reserves)

    @property
    def composition(self) -> dict[str, float]:
        """Return each token's share as a percentage (%)."""
        t = self.total
        return {sym: (r / t * 100) if t > 0 else 0
                for sym, r in zip(self.tokens, self.reserves)}


# ── StableSwap core math ──────────────────────────────────────────────────────

def get_D(reserves: list[float], A: int) -> float:
    """
    Compute the StableSwap invariant D using Newton's method.

    D is n times the amount each token should hold when the pool is perfectly balanced.
    (At equilibrium: x_i = D/n satisfies the invariant)

    Parameters
    ----------
    reserves : list of token reserves
    A        : amplification coefficient

    Returns
    -------
    D : invariant (positive)
    """
    n = len(reserves)
    S = sum(reserves)  # sum of all reserves

    if S == 0:
        return 0.0

    # Initial estimate for D = total sum
    D   = float(S)
    Ann = A * (n ** n)  # A * n^n (constant)

    for _ in range(255):  # up to 255 iterations (guaranteed convergence)
        # D_P = D^(n+1) / (n^n * Π(x_i))
        D_P = D
        for x in reserves:
            D_P = D_P * D / (n * x)

        D_prev = D
        # Newton's method update: D_new = (Ann*S + D_P*n) * D / ((Ann-1)*D + (n+1)*D_P)
        D = (Ann * S + D_P * n) * D / ((Ann - 1) * D + (n + 1) * D_P)

        # Convergence check: stop if change is less than 1e-6
        if abs(D - D_prev) <= 1e-6:
            return D

    return D


def get_y(
    reserves: list[float],
    i: int,
    j: int,
    x_new: float,
    A: int,
) -> float:
    """
    Compute the new balance of token j that preserves the invariant
    when token i's balance changes to x_new.

    This is the core of the swap calculation:
      "If we put x_new of token i into the pool, how much does token j decrease?"
      → (current j balance) - (new j balance) = amount of j we can withdraw

    Parameters
    ----------
    reserves : current reserve list
    i        : index of input token
    j        : index of output token
    x_new    : new balance of token i
    A        : amplification coefficient

    Returns
    -------
    y : new balance of token j
    """
    n   = len(reserves)
    D   = get_D(reserves, A)  # current invariant
    Ann = A * (n ** n)

    # Accumulate reserves for all tokens except j (replace token i with x_new)
    c  = D
    S_ = 0.0

    for k in range(n):
        if k == j:
            continue  # j is what we're solving for
        x_k = x_new if k == i else reserves[k]
        S_ += x_k
        c   = c * D / (n * x_k)  # accumulate D_P

    # c = D^(n+1) / (n^n * Π(x_k for k≠j))
    c = c * D / (n * Ann)
    b = S_ + D / Ann  # constant term

    # Solve for y (new balance of token j) using Newton's method
    y = D
    for _ in range(255):
        y_prev = y
        # Newton update for: y^2 + cy + b*y - D*y - c = 0
        y = (y * y + c) / (2 * y + b - D)

        if abs(y - y_prev) <= 1e-6:
            return y

    return y


# ── Swap simulation ───────────────────────────────────────────────────────────

def simulate_swap(
    pool: PoolState,
    token_in:   str,
    token_out:  str,
    amount_in:  float,
) -> dict:
    """
    Compute the result of a single-pool swap.

    Parameters
    ----------
    pool       : pool state
    token_in   : input token symbol (e.g. "USDC")
    token_out  : output token symbol (e.g. "USDT")
    amount_in  : amount of input token (USD units)

    Returns
    -------
    dict:
      amount_out    : actual output token received
      avg_price     : average fill price (amount_out / amount_in)
      price_impact  : price impact in % (loss vs ideal 1:1 exchange)
      fee_paid      : fee charged
    """
    i = pool.token_index(token_in)
    j = pool.token_index(token_out)

    # New balance of input token after adding amount_in to the pool
    x_new = pool.reserves[i] + amount_in

    # New balance of output token that preserves the invariant
    y_new = get_y(pool.reserves, i, j, x_new, pool.A)

    # Amount receivable before fee
    dy_before_fee = pool.reserves[j] - y_new

    # Deduct fee
    fee_paid   = dy_before_fee * pool.fee
    amount_out = dy_before_fee - fee_paid

    # Price impact: loss vs ideal 1:1 exchange
    ideal_out    = amount_in  # at 1:1, output equals input
    price_impact = (ideal_out - amount_out) / ideal_out * 100

    return {
        "amount_out":   amount_out,
        "avg_price":    amount_out / amount_in,  # closer to 1.0 = better
        "price_impact": price_impact,            # % (lower = better)
        "fee_paid":     fee_paid,
    }


def simulate_split(
    pools:      list[PoolState],
    token_in:   str,
    token_out:  str,
    amount_in:  float,
    n_splits:   int = 100,
) -> dict:
    """
    Find the optimal output by routing across multiple pools (split routing).

    Core aggregator logic:
      "What ratio of the total amount across each pool maximizes output?"

    Parameters
    ----------
    pools     : list of pools (2 or more)
    token_in  : input token
    token_out : output token
    amount_in : total input amount
    n_splits  : number of split ratios to evaluate (higher = more accurate, slower)

    Returns
    -------
    dict:
      total_out     : total output from optimal split
      avg_price     : overall average fill price
      allocations   : amount allocated to each pool {"pool_name": amount}
      vs_single_best: improvement over single best pool (USD)
    """
    # Compute single-pool results first (as baseline)
    single_results = {}
    for pool in pools:
        try:
            res = simulate_swap(pool, token_in, token_out, amount_in)
            single_results[pool.name] = res
        except (ValueError, ZeroDivisionError):
            pass  # skip pools that don't support this token pair

    if not single_results:
        raise ValueError(f"No pool supports {token_in}→{token_out} swap.")

    best_single     = max(single_results.values(), key=lambda r: r["amount_out"])
    best_single_out = best_single["amount_out"]

    # Optimize 2-pool split (most common case)
    # Can be extended to n pools, but 2 is sufficient to demonstrate the concept
    if len(pools) < 2:
        return {
            "total_out":      best_single_out,
            "avg_price":      best_single_out / amount_in,
            "allocations":    {pools[0].name: amount_in},
            "vs_single_best": 0.0,
        }

    # Search for optimal split ratio between pool_a and pool_b
    pool_a, pool_b = pools[0], pools[1]
    best_out   = 0.0
    best_ratio = 0.5  # ratio allocated to pool_a

    # Search 0%~100% in n_splits steps
    for k in range(n_splits + 1):
        ratio = k / n_splits  # fraction going to pool_a
        amt_a = amount_in * ratio
        amt_b = amount_in * (1 - ratio)

        try:
            out_a = simulate_swap(pool_a, token_in, token_out, amt_a)["amount_out"] if amt_a > 0 else 0
            out_b = simulate_swap(pool_b, token_in, token_out, amt_b)["amount_out"] if amt_b > 0 else 0
            total = out_a + out_b

            if total > best_out:
                best_out   = total
                best_ratio = ratio
        except (ValueError, ZeroDivisionError):
            continue

    # Greedily allocate any remaining pools (for extensibility)
    allocated = {
        pool_a.name: amount_in * best_ratio,
        pool_b.name: amount_in * (1 - best_ratio),
    }
    for extra_pool in pools[2:]:
        allocated[extra_pool.name] = 0.0

    improvement = best_out - best_single_out

    return {
        "total_out":      best_out,
        "avg_price":      best_out / amount_in,
        "allocations":    allocated,
        "vs_single_best": improvement,  # additional USD gained via aggregation
    }


# ── Pool state presets ────────────────────────────────────────────────────────

def get_preset_pools(event_name: str, hour_offset: int = 0) -> list[PoolState]:
    """
    Return pool state presets for a given event scenario.
    Use hour_offset to simulate different stages of the event.

    hour_offset = 0 : early stage of event
    hour_offset = 12: peak of event
    hour_offset = 36: recovery begins
    """
    if event_name == "svb":
        # SVB USDC depeg — USDC becomes extremely scarce in Curve 3Pool
        # USDC share decreases and USDT share increases over time
        usdc_pct = max(1.57, 35 - hour_offset * 2.0)  # decreases to 1.57%
        remaining = 100 - usdc_pct
        return [
            PoolState(
                name="Curve 3Pool",
                tokens=["DAI", "USDC", "USDT"],
                reserves=[
                    1_350_000_000 * (remaining / 2) / 100,  # DAI
                    1_350_000_000 * usdc_pct / 100,          # USDC (scarce)
                    1_350_000_000 * (remaining / 2) / 100,  # USDT
                ],
                A=2000,
                fee=0.0004,
            ),
            PoolState(
                name="Uniswap V3 (0.01%)",
                tokens=["USDC", "USDT"],
                # Uniswap less imbalanced than Curve (arbitrageurs partially rebalance)
                reserves=[
                    200_000_000 * max(0.05, (usdc_pct + 10) / 100),
                    200_000_000 * (1 - max(0.05, (usdc_pct + 10) / 100)),
                ],
                A=1,    # Uniswap does not use StableSwap — approximated with A=1
                fee=0.0001,
            ),
        ]

    elif event_name == "usdt":
        # USDT depeg — USDT oversupplied in Curve 3Pool up to 74%
        usdt_pct = min(73.79, 33 + hour_offset * 3.0)
        remaining = 100 - usdt_pct
        return [
            PoolState(
                name="Curve 3Pool",
                tokens=["DAI", "USDC", "USDT"],
                reserves=[
                    520_000_000 * (remaining / 2) / 100,   # DAI
                    520_000_000 * (remaining / 2) / 100,   # USDC
                    520_000_000 * usdt_pct / 100,           # USDT (oversupplied)
                ],
                A=2000,
                fee=0.0004,
            ),
            PoolState(
                name="Uniswap V3 (0.01%)",
                tokens=["USDC", "USDT"],
                reserves=[
                    150_000_000 * (100 - min(60, usdt_pct - 5)) / 100,
                    150_000_000 * min(60, usdt_pct - 5)    / 100,
                ],
                A=1,
                fee=0.0001,
            ),
        ]

    raise ValueError(f"Unknown event: {event_name}")


# ── Run directly to verify ────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=== StableSwap formula test ===")

    # USDT 73% imbalance scenario
    pools = get_preset_pools("usdt", hour_offset=13)
    curve_pool = pools[0]

    print(f"\nPool composition: {curve_pool.composition}")

    amount = 10_000  # $10,000 USDC → USDT swap

    # Single pool
    result_single = simulate_swap(curve_pool, "USDC", "USDT", amount)
    print(f"\nSingle pool (Curve 3Pool):")
    print(f"  USDT received: ${result_single['amount_out']:,.2f}")
    print(f"  Avg fill price: ${result_single['avg_price']:.6f}")
    print(f"  Price impact:  {result_single['price_impact']:.4f}%")

    # Split
    result_split = simulate_split(pools, "USDC", "USDT", amount)
    print(f"\nSplit (Curve + Uniswap):")
    print(f"  USDT received:     ${result_split['total_out']:,.2f}")
    print(f"  Avg fill price:    ${result_split['avg_price']:.6f}")
    print(f"  Improvement vs single: +${result_split['vs_single_best']:.2f}")
    print(f"  Allocation: {result_split['allocations']}")
