# Stablecoin Depeg Dynamics

> On-chain analysis of stablecoin depeg events using Curve 3Pool as an early indicator, with backtested profit strategies and DEX aggregator routing comparison.

---

## Research Overview

This project investigates two real stablecoin depeg events:

| Event | Period | Type | Max Depeg |
|-------|--------|------|-----------|
| SVB bank run | 2023-03-10 ~ 03-15 | External shock | USDC -13% |
| USDT whale dump | 2023-06-14 ~ 06-16 | On-chain whale | USDT -0.38% |

**Key findings:**
- Curve 3Pool composition shifted **hours before** CEX price moved (SVB: ~5 hours early, UST: ~2 days early)
- Peak swap at maximum pool imbalance yielded **+13.01%** on SVB, **+0.34%** on USDT
- Optimal DEX aggregator routing (Curve + Uniswap V3) improved returns by only **+0.07%p** — routing matters far less than pool selection timing
- DEX aggregator algorithm improvement is structurally difficult: I/O latency accounts for **99.99%** of total routing time

---

## Project Structure

```
curve-depeg-analysis/
├── app.py                    # Streamlit dashboard entry point
├── src/
│   ├── fetch_dune.py         # Fetch Curve 3Pool & Uniswap V3 swap data via Dune Analytics
│   ├── fetch_price.py        # Fetch USDC/USDT price from Binance API
│   ├── monitor_curve.py      # Real-time Curve 3Pool state via Ethereum RPC
│   ├── curve_alert.py        # Pool imbalance alert system
│   ├── stableswap.py         # Curve StableSwap invariant implementation
│   ├── backtest.py           # Strategy simulation engine (powers app.py dashboard)
│   └── scripts/
│       ├── aggregator_benchmark.py   # DEX aggregator I/O vs algorithm benchmark
│       ├── backtest_historical.py    # Strategy ① ② backtest on real Dune data
│       └── split_swap_backtest.py    # Curve vs Uniswap V3 VWAP comparison
├── docs/                     # Research documents (5 reports)
│   ├── 01_why_algorithm_improvement_is_hard.md
│   ├── 02_aggregator_routing_loss.md
│   ├── 03_curve_as_depeg_early_indicator.md
│   ├── 04_depeg_profit_strategies.md
│   └── 05_split_swap_aggregation.md
├── data/
│   └── raw/                  # CSV cache from Dune (not tracked in git)
├── .env.example              # Environment variable template
└── requirements.txt
```

---

## Quick Start

```bash
# 1. Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env — add your Dune API key and query IDs

# 4. Fetch on-chain data (requires DUNE_API_KEY in .env)
#    Generates 4 CSV files under data/raw/:
#      curve3pool_swaps_svb.csv   — Curve 3Pool swaps during SVB crisis
#      curve3pool_swaps_usdt.csv  — Curve 3Pool swaps during USDT depeg
#      uniswap_swaps_svb.csv      — Uniswap V3 swaps during SVB crisis
#      uniswap_swaps_usdt.csv     — Uniswap V3 swaps during USDT depeg
python -m src.fetch_dune

# 5. Run backtests
python -m src.scripts.backtest_historical
python -m src.scripts.split_swap_backtest

# 6. Run aggregator benchmark (no data required)
python -m src.scripts.aggregator_benchmark

# 7. Launch dashboard
streamlit run app.py
```

> **No API key?** The backtest scripts can run with pre-cached CSVs in `data/raw/` if you have them. The aggregator benchmark requires no external data at all.

---

## Data Sources

| Source | What | How |
|--------|------|-----|
| [Dune Analytics](https://dune.com) | Curve 3Pool & Uniswap V3 hourly swap data | `src/fetch_dune.py` |
| [Binance API](https://api.binance.com) | USDC/USDT spot price | `src/fetch_price.py` |
| Ethereum RPC | Real-time Curve 3Pool state | `src/monitor_curve.py` |

Dune SQL queries are embedded in `src/fetch_dune.py` — copy them into Dune, save, and paste the query IDs into `.env`.

---

## Strategies Backtested

**Strategy ①: Peak Swap**
Buy the depegged stablecoin at the moment of maximum Curve 3Pool imbalance.
Uses VWAP-based effective fill price from actual on-chain trade data.

**Strategy ②: Anticipation Position**
Enter early when pool composition crosses a threshold (e.g. target token > 38%).
Borrows via Aave — net return calculated after borrowing cost (60% APR during crisis).

| Event | Strategy ① Return | Strategy ② Return |
|-------|-------------------|-------------------|
| SVB   | +13.01%           | +12.42% (38% threshold) |
| USDT  | +0.34%            | negative (interest > gain) |

---

## Research Documents

See [`docs/`](docs/) for the full write-up:

1. [`01_why_algorithm_improvement_is_hard.md`](docs/01_why_algorithm_improvement_is_hard.md) — Why DEX aggregator algorithm improvement is structurally difficult
2. [`02_aggregator_routing_loss.md`](docs/02_aggregator_routing_loss.md) — Three axes of DEX aggregator improvement
3. [`03_curve_as_depeg_early_indicator.md`](docs/03_curve_as_depeg_early_indicator.md) — Curve 3Pool as an early depeg signal
4. [`04_depeg_profit_strategies.md`](docs/04_depeg_profit_strategies.md) — Backtested profit strategies
5. [`05_split_swap_aggregation.md`](docs/05_split_swap_aggregation.md) — Curve vs Uniswap V3 routing comparison

---

## License

MIT
