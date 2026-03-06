"""
fetch_dune.py
─────────────
Fetch hourly Curve 3Pool swap data via Dune Analytics API.

Flow:
  1. Load DUNE_API_KEY and DUNE_QUERY_ID_* from .env
  2. Submit query execution request to Dune REST API
  3. Poll until execution completes
  4. Return results as DataFrame + cache to data/raw/ as CSV

To save Dune SQL queries (see DUNE_SQL_* constants below):
  → Dune website: "New Query" → paste SQL → Save → the number in the URL is the query_id
"""

import os
import time
import json
import requests
import pandas as pd
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
load_dotenv(Path(__file__).parent.parent / ".env")

DUNE_API_KEY = os.getenv("DUNE_API_KEY", "")
BASE_URL = "https://api.dune.com/api/v1"
RAW_DATA_DIR = Path(__file__).parent.parent / "data" / "raw"
RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)


# ── SQL queries to save in Dune (copy and paste into Dune) ───────────────────
#
# [Uniswap V3 pool address]
# USDC/USDT 0.01% fee: 0x3416cf6c708da44db2624d63ea0aaef7113527c6
# → highest-liquidity Uniswap V3 pool for stablecoin swaps
# → used for split-swap comparison against Curve 3Pool

# SVB event query: 2023-03-09 ~ 2023-03-14
# Curve 3Pool address: 0xbebc44782c7db0a1a60cb6fe97d0b483032ff1c7
DUNE_SQL_SVB = """
SELECT
    date_trunc('hour', block_time) AS hour,
    token_bought_symbol,
    token_sold_symbol,
    SUM(token_bought_amount)  AS bought_amount,
    SUM(token_sold_amount)    AS sold_amount,
    COUNT(*)                  AS trade_count
FROM dex.trades
WHERE blockchain = 'ethereum'
    AND project = 'curve'
    AND project_contract_address = 0xbebc44782c7db0a1a60cb6fe97d0b483032ff1c7
    AND block_time BETWEEN TIMESTAMP '2023-03-09 00:00:00'
                       AND TIMESTAMP '2023-03-14 23:59:59'
GROUP BY date_trunc('hour', block_time), token_bought_symbol, token_sold_symbol
ORDER BY hour, token_bought_symbol, token_sold_symbol
"""

# USDT depeg event query: 2023-06-14 ~ 2023-06-16
DUNE_SQL_USDT = """
SELECT
    date_trunc('hour', block_time) AS hour,
    token_bought_symbol,
    token_sold_symbol,
    SUM(token_bought_amount)  AS bought_amount,
    SUM(token_sold_amount)    AS sold_amount,
    COUNT(*)                  AS trade_count
FROM dex.trades
WHERE blockchain        = 'ethereum'
    AND project         = 'Curve'
    AND project_contract_address = 0xbebc44782c7db0a1a60cb6fe97d0b483032ff1c7
    AND block_time BETWEEN TIMESTAMP '2023-06-14 00:00:00'
                       AND TIMESTAMP '2023-06-16 23:59:59'
    AND token_bought_symbol IN ('USDC', 'USDT', 'DAI')
    AND token_sold_symbol   IN ('USDC', 'USDT', 'DAI')
GROUP BY 1, 2, 3
ORDER BY 1, 2, 3
"""


# Uniswap V3 USDC/USDT pool — SVB event (2023-03-09 ~ 2023-03-14)
# Pool address: 0x3416cf6c708da44db2624d63ea0aaef7113527c6 (USDC/USDT 0.01%)
DUNE_SQL_UNI_SVB = """
SELECT
    date_trunc('hour', block_time) AS hour,
    token_bought_symbol,
    token_sold_symbol,
    SUM(token_bought_amount)  AS bought_amount,
    SUM(token_sold_amount)    AS sold_amount,
    COUNT(*)                  AS trade_count
FROM dex.trades
WHERE blockchain = 'ethereum'
    AND project  = 'uniswap'
    AND project_contract_address = 0x3416cf6c708da44db2624d63ea0aaef7113527c6
    AND block_time BETWEEN TIMESTAMP '2023-03-09 00:00:00'
                       AND TIMESTAMP '2023-03-14 23:59:59'
    AND token_bought_symbol IN ('USDC', 'USDT')
    AND token_sold_symbol   IN ('USDC', 'USDT')
GROUP BY 1, 2, 3
ORDER BY 1, 2, 3
"""

# Uniswap V3 USDC/USDT pool — USDT depeg event (2023-06-14 ~ 2023-06-16)
DUNE_SQL_UNI_USDT = """
SELECT
    date_trunc('hour', block_time) AS hour,
    token_bought_symbol,
    token_sold_symbol,
    SUM(token_bought_amount)  AS bought_amount,
    SUM(token_sold_amount)    AS sold_amount,
    COUNT(*)                  AS trade_count
FROM dex.trades
WHERE blockchain = 'ethereum'
    AND project  = 'uniswap'
    AND project_contract_address = 0x3416cf6c708da44db2624d63ea0aaef7113527c6
    AND block_time BETWEEN TIMESTAMP '2023-06-14 00:00:00'
                       AND TIMESTAMP '2023-06-16 23:59:59'
    AND token_bought_symbol IN ('USDC', 'USDT')
    AND token_sold_symbol   IN ('USDC', 'USDT')
GROUP BY 1, 2, 3
ORDER BY 1, 2, 3
"""


# ── Dune REST API helpers ─────────────────────────────────────────────────────


def _headers() -> dict:
    """Return authentication headers."""
    if not DUNE_API_KEY:
        raise ValueError("DUNE_API_KEY not found in .env")
    return {"X-Dune-API-Key": DUNE_API_KEY}


def _execute_query(query_id: int) -> str:
    """
    Execute a saved query and return the execution_id.
    Use the execution_id to poll for results.
    """
    url = f"{BASE_URL}/query/{query_id}/execute"
    resp = requests.post(url, headers=_headers(), timeout=30)
    resp.raise_for_status()
    return resp.json()["execution_id"]


def _poll_execution(execution_id: str, timeout_sec: int = 120) -> dict:
    """
    Poll until the query execution completes.
    Returns the result JSON on completion.
    """
    url = f"{BASE_URL}/execution/{execution_id}/results"
    deadline = time.time() + timeout_sec

    while time.time() < deadline:
        resp = requests.get(url, headers=_headers(), timeout=30)
        resp.raise_for_status()
        data = resp.json()
        state = data.get("state", "")

        if state == "QUERY_STATE_COMPLETED":
            return data  # done

        if state in ("QUERY_STATE_FAILED", "QUERY_STATE_CANCELLED"):
            raise RuntimeError(f"Query execution failed: {state}")

        # Still running → retry after 2 seconds
        print(f"  Query running... ({state})")
        time.sleep(2)

    raise TimeoutError(f"Query did not complete within {timeout_sec} seconds.")


def _results_to_df(data: dict) -> pd.DataFrame:
    """Convert Dune API response JSON to DataFrame."""
    rows = data.get("result", {}).get("rows", [])
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    # Parse 'hour' column as datetime if present
    if "hour" in df.columns:
        df["hour"] = pd.to_datetime(df["hour"], utc=True)

    return df


# ── Public functions ──────────────────────────────────────────────────────────


def fetch_pool_swaps(event_name: str, force_refresh: bool = False) -> pd.DataFrame:
    """
    Fetch Curve 3Pool swap data from Dune.
    Returns cached CSV if available; calls API if missing or force_refresh=True.

    Parameters
    ----------
    event_name    : "svb" or "usdt"
    force_refresh : if True, ignore cache and re-fetch from API

    Returns
    -------
    DataFrame: columns = [hour, token_bought_symbol, token_sold_symbol,
                           bought_amount, sold_amount, trade_count]
    """
    # Load query ID from environment variable for the given event
    env_key_map = {
        "svb": "DUNE_QUERY_ID_SVB",
        "usdt": "DUNE_QUERY_ID_USDT",
    }
    if event_name not in env_key_map:
        raise ValueError(
            f"Unknown event: {event_name}. Available: {list(env_key_map.keys())}"
        )

    query_id = int(os.getenv(env_key_map[event_name], "0"))
    if query_id == 0:
        raise ValueError(
            f"Please set {env_key_map[event_name]} in .env with your Dune query ID.\n"
            f"Save the following SQL in Dune:\n"
            f"{DUNE_SQL_SVB if event_name == 'svb' else DUNE_SQL_USDT}"
        )

    # Cache file path
    cache_path = RAW_DATA_DIR / f"curve3pool_swaps_{event_name}.csv"

    # Return cached data if available
    if cache_path.exists() and not force_refresh:
        print(f"  Loading cache: {cache_path}")
        df = pd.read_csv(cache_path, parse_dates=["hour"])
        df["hour"] = pd.to_datetime(df["hour"], utc=True)
        return df

    # Call Dune API
    print(f"  Executing Dune query (query_id={query_id})...")
    exec_id = _execute_query(query_id)
    data = _poll_execution(exec_id)
    df = _results_to_df(data)

    # Save to CSV cache
    df.to_csv(cache_path, index=False)
    print(f"  Cache saved: {cache_path}")

    return df


def fetch_uniswap_swaps(event_name: str, force_refresh: bool = False) -> pd.DataFrame:
    """
    Fetch Uniswap V3 USDC/USDT pool swap data from Dune.
    Returns cached CSV if available; calls API if missing or force_refresh=True.

    Parameters
    ----------
    event_name    : "svb" or "usdt"
    force_refresh : if True, ignore cache and re-fetch from API

    Returns
    -------
    DataFrame: columns = [hour, token_bought_symbol, token_sold_symbol,
                           bought_amount, sold_amount, trade_count]
    """
    env_key_map = {
        "svb":  "DUNE_QUERY_ID_UNI_SVB",
        "usdt": "DUNE_QUERY_ID_UNI_USDT",
    }
    if event_name not in env_key_map:
        raise ValueError(
            f"Unknown event: {event_name}. Available: {list(env_key_map.keys())}"
        )

    query_id = int(os.getenv(env_key_map[event_name], "0"))
    if query_id == 0:
        raise ValueError(
            f"Please set {env_key_map[event_name]} in .env with your Dune query ID.\n"
            f"Save the following SQL in Dune:\n"
            f"{DUNE_SQL_UNI_SVB if event_name == 'svb' else DUNE_SQL_UNI_USDT}"
        )

    cache_path = RAW_DATA_DIR / f"uniswap_swaps_{event_name}.csv"

    if cache_path.exists() and not force_refresh:
        print(f"  Loading cache: {cache_path}")
        df = pd.read_csv(cache_path, parse_dates=["hour"])
        df["hour"] = pd.to_datetime(df["hour"], utc=True)
        return df

    print(f"  Executing Dune query (query_id={query_id})...")
    exec_id = _execute_query(query_id)
    data    = _poll_execution(exec_id)
    df      = _results_to_df(data)

    df.to_csv(cache_path, index=False)
    print(f"  Cache saved: {cache_path}")

    return df


def compute_pool_composition(swap_df: pd.DataFrame, event_name: str) -> pd.DataFrame:
    """
    Estimate hourly pool composition from swap event data.

    Method:
      - Start from known initial reserves just before the event
      - Accumulate net inflows/outflows for each hour to track balances

    Returns
    -------
    DataFrame: columns = [hour, usdc_reserve, usdt_reserve, dai_reserve,
                           usdc_pct, usdt_pct, dai_pct, total]
    """
    # Initial reserves just before each event (approximate real values)
    initial_reserves = {
        "svb": {
            # Curve 3Pool reserves as of 2023-03-09 (just before SVB event), in USD
            "usdc": 350_000_000,
            "usdt": 500_000_000,
            "dai": 500_000_000,
        },
        "usdt": {
            # Curve 3Pool reserves as of 2023-06-14 (just before USDT depeg)
            "usdc": 160_000_000,
            "usdt": 200_000_000,
            "dai": 160_000_000,
        },
    }

    reserves = dict(initial_reserves[event_name])  # work on a copy

    if swap_df.empty:
        return pd.DataFrame()

    # Group by hour and apply net inflows/outflows
    hours = sorted(swap_df["hour"].unique())
    rows = []

    for hour in hours:
        hour_swaps = swap_df[swap_df["hour"] == hour]

        # Apply each swap to pool reserves
        for _, row in hour_swaps.iterrows():
            bought = row["token_bought_symbol"].lower()  # token leaving the pool
            sold = row["token_sold_symbol"].lower()      # token entering the pool

            if sold in reserves:
                reserves[sold] += row["sold_amount"]     # inflow
            if bought in reserves:
                reserves[bought] -= row["bought_amount"] # outflow

        # Clip to zero to prevent negative balances (data noise)
        reserves = {k: max(v, 0) for k, v in reserves.items()}

        total = sum(reserves.values())
        if total == 0:
            continue

        rows.append(
            {
                "hour": hour,
                "usdc_reserve": reserves["usdc"],
                "usdt_reserve": reserves["usdt"],
                "dai_reserve": reserves["dai"],
                "usdc_pct": reserves["usdc"] / total * 100,
                "usdt_pct": reserves["usdt"] / total * 100,
                "dai_pct": reserves["dai"] / total * 100,
                "total": total,
            }
        )

    return pd.DataFrame(rows)


# ── Run directly to verify ────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=== Dune data load test ===")
    print("(Error expected if query ID is not set in .env — this is normal)")
    try:
        df = fetch_pool_swaps("svb")
        print(df.head())
        comp = compute_pool_composition(df, "svb")
        print("\nPool composition:")
        print(comp.head(10))
    except ValueError as e:
        print(f"Configuration needed: {e}")
