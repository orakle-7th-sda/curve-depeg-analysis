"""
aggregator_benchmark.py
───────────────────────
Benchmark demonstrating why improving DEX aggregator algorithms is hard in practice.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Scenario Assumptions
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Pool configuration (modeled after major Solana DEXes, USDC → USDT swap):
  - Orca      TVL ~$10M  fee 0.01%  (Largest CLMM DEX on Solana)
  - Raydium   TVL ~$6.4M fee 0.25%  (Hybrid AMM + orderbook)
  - Lifinity  TVL ~$3.6M fee 0.02%  (Proactive Market Maker)
  - Meteora   TVL ~$5.0M fee 0.05%  (Dynamic AMM)
  - Phoenix   TVL ~$8.2M fee 0.03%  (Orderbook DEX)
  - Saber     TVL ~$10M  fee 0.01%  (Stablecoin-specialized AMM)

Assumptions:
  - Swap size: $10,000 (USDC → USDT)
  - Network latency: 200ms per pool (assuming real-time RPC queries)

  ※ Note: Jupiter's actual internal architecture is not publicly disclosed.
    It may use pre-indexing, gRPC streaming, or other methods beyond real-time RPC.
    This simulation is intended to illustrate the ratio of algorithm compute time
    vs I/O wait time under a "real-time RPC" assumption, and may differ from reality.

  - Benchmark 2 mid-run intervention: a large trader ($80,000) enters the
    best pool first → pool state changes → optimal pool differs on second run

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Benchmark Results (example output)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[Benchmark 1] I/O vs algorithm time ratio
  API calls (I/O, simulated network latency):  1219.3 ms   ← 99.99% of total
  Path-finding algorithm (CPU):                   0.1 ms   ←  0.009% of total
  Even if algorithm runs 2x faster:                        total time reduced by 0.004%
  → User-perceptible improvement: none

[Benchmark 2] Reproducibility — same algorithm, different results
  Run 1: 9,999.0 USDT  (selected pool: Saber USDC/USDT)
  Run 2: 9,995.0 USDT  (selected pool: Orca  USDC/USDT)  ← pool changed too
  Diff:      3.99 USDT  (0.04%)
  Cause: algorithm difference? or mid-run pool state change? → indistinguishable
  → Jupiter Metis source not public → no baseline control → superiority cannot be proven

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Usage
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  python -m src.scripts.aggregator_benchmark

  No external dependencies — no API keys or data files required.
  Uses only Python standard library (time, math, random).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Configurable parameters (make_pools / __main__ block)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  amount_in         : swap size in USD (default $10,000)
  latency           : simulated network delay per pool in seconds (default 0.2 = 200ms)
  noise_trades      : number of noise transactions in Benchmark 2 (default 3)
  large trade size  : 80,000 USD (hardcoded inside benchmark_reproducibility)

  To modify pool parameters, edit make_pools() directly:
    reserve_a, reserve_b  — initial pool reserves (USD)
    fee                   — swap fee (e.g. 0.0001 = 0.01%)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import time
import math
import random


# ── MockPool ──────────────────────────────────────────────────────────────────

class MockPool:
    """
    Simple AMM pool (Uniswap v2 constant product: x * y = k).

    Parameters
    ----------
    name      : pool name (e.g. "Orca USDC/USDT")
    reserve_a : token A reserve
    reserve_b : token B reserve
    fee       : swap fee (e.g. 0.003 = 0.3%)
    latency   : simulated API response delay (seconds)
    """

    def __init__(
        self,
        name: str,
        reserve_a: float,
        reserve_b: float,
        fee: float = 0.003,
        latency: float = 0.2,
    ):
        self.name = name
        self.reserve_a = reserve_a
        self.reserve_b = reserve_b
        self.fee = fee
        self.latency = latency

    def get_quote(self, amount_in: float) -> float:
        """
        Compute token B output for a given token A input.
        Simulates network I/O latency via time.sleep.
        """
        time.sleep(self.latency)  # ← simulates real API call latency

        amount_in_with_fee = amount_in * (1 - self.fee)
        amount_out = (
            self.reserve_b * amount_in_with_fee
            / (self.reserve_a + amount_in_with_fee)
        )
        return amount_out

    def apply_swap(self, amount_in: float) -> float:
        """Execute the swap and update pool state."""
        amount_out = self.get_quote(amount_in)
        self.reserve_a += amount_in
        self.reserve_b -= amount_out
        return amount_out

    @property
    def price(self) -> float:
        return self.reserve_b / self.reserve_a


# ── MockAggregator ────────────────────────────────────────────────────────────

class MockAggregator:
    """
    Simple aggregator that iterates over MockPools to find the best route (max output).

    Search strategy: exhaustive search (compare quotes from all pools, select best)
    """

    def __init__(self, pools: list[MockPool]):
        self.pools = pools

    def find_best_route(self, amount_in: float) -> dict:
        """
        Collect quotes from all pools and select the optimal one.

        Returns
        -------
        dict:
            best_pool   : selected pool
            amount_out  : expected output
            quotes      : full per-pool quotes
            algo_time   : path-finding algorithm time (ms)
            io_time     : API call (I/O) time (ms)
        """
        quotes = {}

        # ── I/O phase: query each pool ────────────────────────────────────────
        io_start = time.perf_counter()
        for pool in self.pools:
            quotes[pool.name] = pool.get_quote(amount_in)
        io_time = (time.perf_counter() - io_start) * 1000  # ms

        # ── Algorithm phase: select best pool ─────────────────────────────────
        algo_start = time.perf_counter()
        best_pool_name = max(quotes, key=quotes.__getitem__)
        best_pool = next(p for p in self.pools if p.name == best_pool_name)
        amount_out = quotes[best_pool_name]
        algo_time = (time.perf_counter() - algo_start) * 1000  # ms

        return {
            "best_pool":  best_pool,
            "amount_out": amount_out,
            "quotes":     quotes,
            "algo_time":  algo_time,
            "io_time":    io_time,
        }


# ── Pool set creation ─────────────────────────────────────────────────────────

def make_pools(latency: float = 0.2) -> list[MockPool]:
    """Return 6 pools modeled after real Solana DEXes."""
    return [
        MockPool("Orca USDC/USDT",     reserve_a=5_000_000, reserve_b=5_008_000, fee=0.0001, latency=latency),
        MockPool("Raydium USDC/USDT",  reserve_a=3_200_000, reserve_b=3_195_000, fee=0.0025, latency=latency),
        MockPool("Lifinity USDC/USDT", reserve_a=1_800_000, reserve_b=1_802_000, fee=0.0002, latency=latency),
        MockPool("Meteora USDC/USDT",  reserve_a=2_500_000, reserve_b=2_498_000, fee=0.0005, latency=latency),
        MockPool("Phoenix USDC/USDT",  reserve_a=4_100_000, reserve_b=4_105_000, fee=0.0003, latency=latency),
        MockPool("Saber USDC/USDT",    reserve_a=5_020_000, reserve_b=5_030_000, fee=0.0001, latency=latency),
    ]


# ── Benchmark 1: I/O vs algorithm time ratio ──────────────────────────────────

def benchmark_io_vs_compute(amount_in: float = 10_000.0) -> None:
    """
    Demonstrates argument 3:
    Measures the ratio of path-finding algorithm time vs API I/O time.
    Shows that algorithm optimization has negligible impact on overall performance.
    """
    print("=" * 60)
    print("  [Benchmark 1] I/O vs Algorithm Time Ratio")
    print("=" * 60)
    print(f"  Swap size: ${amount_in:,.0f}  |  Pools: 6")
    print()

    pools = make_pools(latency=0.2)
    agg   = MockAggregator(pools)

    result = agg.find_best_route(amount_in)

    total_time = result["io_time"] + result["algo_time"]
    algo_ratio = result["algo_time"] / total_time * 100

    print("  [Pool Quotes]")
    for pool_name, quote in result["quotes"].items():
        marker = " ← selected" if pool_name == result["best_pool"].name else ""
        print(f"    {pool_name:<30}  {quote:>12,.4f} USDT{marker}")

    print()
    print("  [Time Breakdown]")
    print(f"    API calls (I/O, simulated network latency): {result['io_time']:>8.1f} ms")
    print(f"    Path-finding algorithm (CPU):               {result['algo_time']:>8.4f} ms")
    print(f"    Total:                                      {total_time:>8.1f} ms")
    print()
    print(f"  [Conclusion] Algorithm share: {algo_ratio:.3f}%")
    print(f"               2x faster algorithm → total time reduced by {algo_ratio/2:.3f}%")
    print(f"               User-perceptible improvement: none")
    print()


# ── Benchmark 2: Reproducibility — same algorithm, different results ───────────

def benchmark_reproducibility(
    amount_in: float = 10_000.0,
    noise_trades: int = 3,
) -> None:
    """
    Demonstrates arguments 1 and 2:
    Runs the same trade twice using the same algorithm.
    Between runs, other transactions subtly change pool state.
    Shows that the cause of result differences cannot be isolated to the algorithm.
    """
    print("=" * 60)
    print("  [Benchmark 2] Reproducibility — Same Algorithm, Different Results")
    print("=" * 60)
    print(f"  Swap size: ${amount_in:,.0f}")
    print(f"  Mid-run noise transactions: {noise_trades} (simulating other users)")
    print()

    pools = make_pools(latency=0.0)  # remove latency to isolate other variables

    # Run 1
    agg1    = MockAggregator(pools)
    result1 = agg1.find_best_route(amount_in)
    out1    = result1["amount_out"]
    pool1   = result1["best_pool"].name

    # Between runs: other users' transactions change pool state
    # Large swap concentrated on the best pool → liquidity consumed
    rng = random.Random(42)
    best_pool_ref = result1["best_pool"]
    best_pool_ref.apply_swap(80_000)   # large trader front-runs our trade
    for _ in range(noise_trades):
        pool = rng.choice(pools)
        noise_amount = rng.uniform(500, 5_000)
        pool.apply_swap(noise_amount)

    # Run 2 (same algorithm)
    agg2    = MockAggregator(pools)
    result2 = agg2.find_best_route(amount_in)
    out2    = result2["amount_out"]
    pool2   = result2["best_pool"].name

    diff     = abs(out1 - out2)
    diff_pct = diff / out1 * 100

    print("  [Results]")
    print(f"    Run 1:   {out1:>12,.4f} USDT  (selected pool: {pool1})")
    print(f"    Run 2:   {out2:>12,.4f} USDT  (selected pool: {pool2})")
    print()
    print(f"  [Difference] {diff:.4f} USDT  ({diff_pct:.4f}%)")
    print()
    print("  [Conclusion]")
    print("    Same algorithm, same input → different results")
    print()
    print("  [Root Cause Candidates — Uncontrollable Variables]")
    print("    A. Algorithm difference")
    print("       → The variable we want to test. But inseparable from B–E below.")
    print()
    print("    B. Pool state changes constantly")
    print("       → Other users' trades can always intervene between")
    print("          quote collection and transaction settlement.")
    print("          On Solana, blocks are produced every 400ms — hundreds of txs in between.")
    print()
    print("    C. Network congestion")
    print("       → Even the same pool at the same moment can return different")
    print("          quotes depending on RPC node response time.")
    print("          Under congestion, some quotes may arrive stale.")
    print()
    print("    D. MEV (Maximal Extractable Value) bot interference")
    print("       → Bots detect large trades and front-run them,")
    print("          altering pool state before our transaction settles.")
    print("          Degrades results regardless of algorithm quality.")
    print()
    print("    E. Slippage tolerance settings")
    print("       → If slippage tolerance differs from the comparison target (Jupiter),")
    print("          the same route can produce different settlement outcomes.")
    print()
    print("  [Fundamental Limitation of Jupiter Comparison]")
    print("    Jupiter Metis engine source code is not public.")
    print("    → Parameters, weights, and search depth are unknown.")
    print("    → No way to control B–E equally and isolate A alone.")
    print("    → Algorithmic superiority cannot be objectively proven.")
    print()


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    benchmark_io_vs_compute(amount_in=10_000)
    benchmark_reproducibility(amount_in=10_000, noise_trades=3)
