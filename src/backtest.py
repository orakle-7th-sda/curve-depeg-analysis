"""
backtest.py
───────────
Backtesting logic for Strategy ② and Strategy ③.

Strategy ②: AMM reverse swap + multi-pool split
  "When USDT is 73% of Curve 3Pool, compare single DEX vs aggregator split"
  → For the same swap amount, how much more USDT does the aggregator return?

Strategy ③: Anticipation position
  "Enter short when Curve 3Pool share exceeds a threshold → profit if depeg occurs"
  → How does return vary by signal threshold?
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Optional

from .stableswap import PoolState, simulate_swap, simulate_split, get_preset_pools


# ── Shared configuration ──────────────────────────────────────────────────────

# Annual borrow rate used in Strategy ③ simulation (Aave USDT)
AAVE_BORROW_APR = 0.05         # 5% APR (normal conditions)
AAVE_BORROW_APR_CRISIS = 0.60  # 60% APR (during depeg panic)


# ── Strategy ② backtest ───────────────────────────────────────────────────────

@dataclass
class Strategy2Result:
    """Single simulation result for Strategy ②."""
    amount_in:         float   # input amount (USD)
    single_out:        float   # output from single pool
    split_out:         float   # output from split routing
    improvement:       float   # improvement amount (split - single)
    improvement_pct:   float   # improvement percentage (%)
    pool_composition:  dict    # pool composition at the time
    allocations:       dict    # split allocation breakdown


def backtest_strategy2(
    event_name:   str,
    amount_in:    float = 10_000,
    hour_steps:   int   = 20,
) -> pd.DataFrame:
    """
    Strategy ②: Compare single pool vs split routing performance across the event timeline.

    Iterates hour_offset from 0 to hour_steps and records swap results at each stage.

    Parameters
    ----------
    event_name : "svb" or "usdt"
    amount_in  : swap amount (USD)
    hour_steps : number of event progression steps

    Returns
    -------
    DataFrame: hourly single vs split performance comparison
    """
    rows = []

    for hour_offset in range(hour_steps + 1):
        pools = get_preset_pools(event_name, hour_offset)
        curve_pool = pools[0]

        # Compute pool composition
        composition = curve_pool.composition

        # Determine swap direction
        # SVB: USDT → USDC (USDC is cheap, so we buy USDC by selling USDT)
        # USDT: USDC → USDT (USDT is cheap, so we buy USDT by selling USDC)
        if event_name == "svb":
            token_in, token_out = "USDT", "USDC"  # USDC undervalued → buy USDC
        else:
            token_in, token_out = "USDC", "USDT"  # USDT undervalued → buy USDT

        # Single pool simulation
        try:
            single_result = simulate_swap(curve_pool, token_in, token_out, amount_in)
            single_out    = single_result["amount_out"]
            single_price  = single_result["avg_price"]
        except (ValueError, ZeroDivisionError):
            continue

        # Split simulation (Curve + Uniswap)
        try:
            split_result = simulate_split(pools, token_in, token_out, amount_in)
            split_out    = split_result["total_out"]
            split_price  = split_result["avg_price"]
            allocations  = split_result["allocations"]
        except (ValueError, ZeroDivisionError):
            continue

        improvement     = split_out - single_out
        improvement_pct = improvement / single_out * 100 if single_out > 0 else 0

        rows.append({
            "hour_offset":       hour_offset,
            "pool_usdt_pct":     composition.get("USDT", 0),
            "pool_usdc_pct":     composition.get("USDC", 0),
            "amount_in":         amount_in,
            "single_out":        single_out,
            "single_avg_price":  single_price,
            "split_out":         split_out,
            "split_avg_price":   split_price,
            "improvement_usd":   improvement,
            "improvement_pct":   improvement_pct,
            "curve_allocation":  allocations.get("Curve 3Pool", 0),
            "uniswap_allocation":allocations.get("Uniswap V3 (0.01%)", 0),
        })

    return pd.DataFrame(rows)


def analyze_price_impact_by_size(
    event_name: str,
    hour_offset: int,
    amounts: Optional[list[float]] = None,
) -> pd.DataFrame:
    """
    Analyze price impact difference between single pool and split routing
    across a range of trade sizes.
    Demonstrates that split routing becomes more effective at larger sizes.

    Parameters
    ----------
    event_name  : "svb" or "usdt"
    hour_offset : event progression stage
    amounts     : list of trade sizes to analyze (default: $1k~$1M)

    Returns
    -------
    DataFrame: price impact comparison by trade size
    """
    if amounts is None:
        # 20 log-scale points from $1k to $1M
        amounts = [10 ** x for x in np.linspace(3, 6, 20)]

    pools = get_preset_pools(event_name, hour_offset)
    curve_pool = pools[0]

    token_in  = "USDC" if event_name == "usdt" else "USDT"
    token_out = "USDT" if event_name == "usdt" else "USDC"

    rows = []
    for amt in amounts:
        try:
            single = simulate_swap(curve_pool, token_in, token_out, amt)
            split  = simulate_split(pools, token_in, token_out, amt)

            rows.append({
                "amount_in":            amt,
                "single_price_impact":  single["price_impact"],
                "split_price_impact":   (amt - split["total_out"]) / amt * 100,
                "improvement_pct":      (split["total_out"] - single["amount_out"]) / single["amount_out"] * 100,
                "single_out":           single["amount_out"],
                "split_out":            split["total_out"],
            })
        except (ValueError, ZeroDivisionError):
            continue

    return pd.DataFrame(rows)


# ── Strategy ③ backtest ───────────────────────────────────────────────────────

@dataclass
class SignalEntry:
    """Entry information recorded when a Strategy ③ signal fires."""
    hour_offset:   int
    pool_ratio:    float   # pool ratio at signal time (%)
    entry_price:   float   # swap price at entry (short entry price)
    borrow_apr:    float   # applied borrow interest rate


@dataclass
class Strategy3Result:
    """Single simulation result for Strategy ③."""
    signal_threshold:  float   # entry signal threshold (%)
    entry:             Optional[SignalEntry]
    exit_hour:         Optional[int]
    gross_pnl_pct:     float   # gross return before fees/interest (%)
    borrow_cost_pct:   float   # borrow interest cost (%)
    net_pnl_pct:       float   # net return (%)
    holding_hours:     int     # holding duration in hours
    signal_triggered:  bool    # whether signal actually fired


def backtest_strategy3(
    price_df:           pd.DataFrame,
    composition_df:     Optional[pd.DataFrame] = None,
    event_name:         str = "usdt",
    thresholds:         Optional[list[float]] = None,
    max_holding_hours:  int = 168,  # max 7 days
    exit_target_price:  float = 0.999,  # target exit price
) -> pd.DataFrame:
    """
    Strategy ③: Backtest anticipation short position across pool composition thresholds.

    Signal logic:
      1. When target token share exceeds threshold% → enter short
         (borrow target token on Aave → swap to stable counterpart)
      2. Exit when token price recovers to exit_target_price or max_holding_hours reached
      3. Net return = (entry price - exit price) - borrow interest

    Parameters
    ----------
    price_df           : price DataFrame from fetch_price.py
                         columns = [timestamp, usdc, usdt, dai]
    composition_df     : pool composition DataFrame from Dune (optional; uses price if absent)
    event_name         : "svb" or "usdt"
    thresholds         : pool share thresholds to test (default: [45, 55, 60, 65, 70])
    max_holding_hours  : maximum holding period (force-exit after this)
    exit_target_price  : price level at which to take profit

    Returns
    -------
    DataFrame: return comparison across thresholds
    """
    if thresholds is None:
        thresholds = [45.0, 55.0, 60.0, 65.0, 70.0]

    # Sort price_df by time
    price_df = price_df.sort_values("timestamp").reset_index(drop=True)

    # Normalize column names to lowercase
    price_df.columns = [c.lower() for c in price_df.columns]
    price_col = "usdt" if event_name == "usdt" else "usdc"
    if price_col not in price_df.columns:
        raise ValueError(f"'{price_col}' column not found in price_df. Existing columns: {list(price_df.columns)}")

    results = []

    for threshold in thresholds:
        # Use pool composition data or fall back to price-based approximation
        signal_triggered = False
        entry_price      = None
        entry_idx        = None
        entry_ratio      = None

        for idx, row in price_df.iterrows():
            price = row[price_col]

            # Determine pool ratio: use actual composition data if available
            if composition_df is not None and not composition_df.empty:
                nearest = _find_nearest_composition(composition_df, row["timestamp"])
                ratio   = nearest.get("usdt_pct" if event_name == "usdt" else "usdc_pct", 33.0)
            else:
                # Approximate pool ratio from price when composition data is absent
                ratio = _estimate_pool_ratio_from_price(price, event_name)

            # Check signal condition
            if not signal_triggered and ratio >= threshold:
                signal_triggered = True
                entry_price      = price
                entry_idx        = idx
                entry_ratio      = ratio

        if not signal_triggered or entry_price is None:
            # Signal never fired
            results.append({
                "threshold":       threshold,
                "signal_triggered":False,
                "entry_ratio":     None,
                "entry_price":     None,
                "exit_price":      None,
                "holding_hours":   0,
                "gross_pnl_pct":   0.0,
                "borrow_cost_pct": 0.0,
                "net_pnl_pct":     0.0,
            })
            continue

        # Search for exit point after entry
        exit_price  = None
        exit_idx    = entry_idx
        holding_hrs = 0

        subsequent = price_df.iloc[entry_idx + 1:]
        for idx2, row2 in subsequent.iterrows():
            holding_hrs = idx2 - entry_idx  # approximation
            current_price = row2[price_col]

            # Exit condition 1: price recovers to target
            if current_price >= exit_target_price:
                exit_price = current_price
                break

            # Exit condition 2: max holding period reached
            if holding_hrs >= max_holding_hours:
                exit_price = current_price
                break

        if exit_price is None:
            exit_price  = price_df[price_col].iloc[-1]
            holding_hrs = len(subsequent)

        # Return calculation
        # Short position: sell at entry_price, buy back at exit_price
        gross_pnl_pct = (entry_price - exit_price) / entry_price * 100

        # Borrow interest cost (higher rate during depeg panic)
        borrow_apr      = AAVE_BORROW_APR_CRISIS if ratio > 65 else AAVE_BORROW_APR
        holding_days    = holding_hrs / 24.0
        borrow_cost_pct = borrow_apr / 365 * holding_days * 100

        net_pnl_pct = gross_pnl_pct - borrow_cost_pct

        results.append({
            "threshold":       threshold,
            "signal_triggered":True,
            "entry_ratio":     entry_ratio,
            "entry_price":     entry_price,
            "exit_price":      exit_price,
            "holding_hours":   holding_hrs,
            "gross_pnl_pct":   round(gross_pnl_pct, 4),
            "borrow_cost_pct": round(borrow_cost_pct, 4),
            "net_pnl_pct":     round(net_pnl_pct, 4),
        })

    return pd.DataFrame(results)


def _find_nearest_composition(comp_df: pd.DataFrame, timestamp) -> dict:
    """
    Return the pool composition entry closest in time to the given timestamp.
    """
    if comp_df.empty:
        return {}
    time_col = "hour" if "hour" in comp_df.columns else comp_df.columns[0]
    diffs = abs(comp_df[time_col] - timestamp)
    nearest_idx = diffs.idxmin()
    return comp_df.iloc[nearest_idx].to_dict()


def _estimate_pool_ratio_from_price(price: float, event_name: str) -> float:
    """
    Approximate pool ratio from price data when Dune composition data is unavailable.
    Fallback for offline use.

    USDT depeg: price below $0.99 implies USDT oversupply in pool
    SVB USDC depeg: price below $0.97 implies USDC becoming scarce
    """
    if event_name == "usdt":
        # USDT price $1.000 → ratio ~33% (normal)
        # USDT price $0.977 → ratio ~74% (maximum imbalance)
        if price >= 1.000:
            return 33.0
        ratio = 33.0 + (1.000 - price) / 0.023 * 41.0
        return min(ratio, 74.0)
    else:  # svb (USDC)
        if price >= 1.000:
            return 33.0
        ratio = 33.0 - (1.000 - price) / 0.13 * 31.0  # USDC share decreases
        return max(ratio, 1.57)


# ── Combined analysis function ────────────────────────────────────────────────

def run_full_analysis(
    event_name: str,
    price_df: pd.DataFrame,
    composition_df: Optional[pd.DataFrame] = None,
    swap_amount: float = 10_000,
) -> dict:
    """
    Run Strategy ② and Strategy ③ in one call and return all results.

    Returns
    -------
    dict:
      "strategy2_timeline"    : hourly single vs split performance
      "strategy2_by_size"     : price impact comparison by trade size
      "strategy3_thresholds"  : anticipation strategy returns by threshold
    """
    print(f"[{event_name.upper()}] Running Strategy ② backtest...")
    s2_timeline = backtest_strategy2(event_name, amount_in=swap_amount)

    print(f"[{event_name.upper()}] Running Strategy ② trade size analysis...")
    s2_by_size = analyze_price_impact_by_size(event_name, hour_offset=12)

    print(f"[{event_name.upper()}] Running Strategy ③ backtest...")
    s3_results = backtest_strategy3(
        price_df       = price_df,
        composition_df = composition_df,
        event_name     = event_name,
    )

    return {
        "strategy2_timeline":   s2_timeline,
        "strategy2_by_size":    s2_by_size,
        "strategy3_thresholds": s3_results,
    }


# ── Run directly to verify ────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))

    print("=== Strategy ② backtest test (USDT depeg event) ===")
    df2 = backtest_strategy2("usdt", amount_in=50_000, hour_steps=15)
    print(df2[["hour_offset", "pool_usdt_pct", "single_out", "split_out",
               "improvement_usd", "improvement_pct"]].to_string())

    print("\n=== Strategy ② trade size analysis ===")
    df_size = analyze_price_impact_by_size("usdt", hour_offset=12)
    print(df_size[["amount_in", "single_price_impact",
                   "split_price_impact", "improvement_pct"]].to_string())
