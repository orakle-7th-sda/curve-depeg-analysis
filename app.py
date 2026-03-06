"""
app.py
──────
Streamlit dashboard entry point.

Tabs:
  [1] Event Overview    : price chart + depeg timeline
  [2] Strategy ②       : AMM reverse swap — single pool vs aggregator split comparison
  [3] Strategy ③       : Anticipation position — return analysis by signal threshold

Usage:
  streamlit run app.py
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots

from src.fetch_price  import fetch_event_prices, compute_depeg_stats, EVENTS
from src.fetch_dune   import fetch_pool_swaps, compute_pool_composition
from src.backtest     import (
    backtest_strategy2,
    analyze_price_impact_by_size,
    backtest_strategy3,
)
from src.monitor_curve import get_pool_state


# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Stablecoin Depeg × Aggregator",
    page_icon="📊",
    layout="wide",
)

st.title("📊 Stablecoin Depeg Dynamics × DEX Aggregator")
st.caption("Analyzing the real-world advantage of aggregators in on-chain depeg strategies")


# ── Sidebar: event selection ──────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Settings")

    event_label = st.selectbox(
        "Select Event",
        options=list(EVENTS.keys()),
        index=0,
    )
    event_name = "svb" if "SVB" in event_label else "usdt"
    event_info = EVENTS[event_label]

    st.info(event_info["desc"])
    st.divider()

    swap_amount = st.number_input(
        "Swap Amount (USD)",
        min_value=1_000,
        max_value=10_000_000,
        value=50_000,
        step=1_000,
        help="Swap size to simulate in Strategy ②",
    )

    use_dune = st.toggle(
        "Use Dune Pool Composition Data",
        value=False,
        help="OFF: approximate pool ratio from price data / ON: use real pool composition from Dune API (requires query ID)",
    )


# ── Data loading (cached) ─────────────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner="Loading price data from CoinGecko...")
def load_price_data(event_label: str) -> pd.DataFrame:
    """Load CoinGecko price data (cached 1 hour)."""
    return fetch_event_prices(event_label)


@st.cache_data(ttl=3600, show_spinner="Loading pool composition data from Dune...")
def load_composition_data(event_name: str):
    """Load Dune pool composition data."""
    try:
        swap_df = fetch_pool_swaps(event_name)
        comp_df = compute_pool_composition(swap_df, event_name)
        return comp_df
    except (ValueError, Exception) as e:
        return None, str(e)


# Load price data
try:
    price_df = load_price_data(event_label)
    price_loaded = True
except Exception as e:
    st.error(f"Failed to load price data: {e}")
    price_loaded = False
    price_df = pd.DataFrame()

# Pool composition data (Dune, optional)
comp_df = None
if use_dune:
    result = load_composition_data(event_name)
    if isinstance(result, tuple):
        comp_df, err_msg = result
        if err_msg:
            st.sidebar.warning(f"Dune data load failed: {err_msg}\nFalling back to price-based approximation")
    else:
        comp_df = result


# ── Tab layout ────────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4 = st.tabs([
    "📈 Event Overview",
    "⚖️ Strategy ② : AMM Split",
    "🎯 Strategy ③ : Anticipation",
    "🔴 Live Curve Monitor",
])


# ══════════════════════════════════════════════════════════════════════════════
# Tab 1: Event Overview
# ══════════════════════════════════════════════════════════════════════════════
with tab1:
    st.subheader(f"Event: {event_label}")

    if not price_loaded or price_df.empty:
        st.warning("Price data could not be loaded.")
    else:
        # Depeg stats metrics
        stats = compute_depeg_stats(price_df)
        cols  = st.columns(len(stats))
        for col, (symbol, s) in zip(cols, stats.items()):
            col.metric(
                label=f"{symbol} Lowest Price",
                value=f"${s['min_price']:.4f}",
                delta=f"{s['max_drawdown']:.4f}%",
                delta_color="inverse",
            )

        st.divider()

        # Price chart
        fig = go.Figure()

        colors = {"usdc": "#2775CA", "usdt": "#26A17B", "dai": "#F4B731"}
        for col_name, color in colors.items():
            if col_name in price_df.columns:
                fig.add_trace(go.Scatter(
                    x=price_df["timestamp"],
                    y=price_df[col_name],
                    mode="lines",
                    name=col_name.upper(),
                    line=dict(color=color, width=2),
                ))

        # Peg reference line ($1.00)
        fig.add_hline(
            y=1.0,
            line_dash="dash",
            line_color="gray",
            annotation_text="Peg ($1.00)",
        )

        fig.update_layout(
            title="Stablecoin Price Timeline",
            xaxis_title="Time (UTC)",
            yaxis_title="Price (USD)",
            hovermode="x unified",
            height=400,
        )
        st.plotly_chart(fig, use_container_width=True)

        # Pool composition chart (when Dune data is available)
        if comp_df is not None and not comp_df.empty:
            st.subheader("Curve 3Pool Composition")
            fig2 = go.Figure()
            for token, color in [("usdc_pct", "#2775CA"), ("usdt_pct", "#26A17B"), ("dai_pct", "#F4B731")]:
                if token in comp_df.columns:
                    fig2.add_trace(go.Scatter(
                        x=comp_df["hour"],
                        y=comp_df[token],
                        mode="lines",
                        name=token.replace("_pct", "").upper(),
                        line=dict(color=color),
                        stackgroup="one",  # stacked area chart
                    ))
            fig2.add_hline(y=33.3, line_dash="dash", line_color="white",
                           annotation_text="Balanced (33.3%)")
            fig2.update_layout(
                title="Curve 3Pool Token Share (%)",
                xaxis_title="Time (UTC)",
                yaxis_title="Share (%)",
                height=350,
            )
            st.plotly_chart(fig2, use_container_width=True)
        else:
            st.info("Pool composition chart: enable 'Use Dune Pool Composition Data' in the sidebar to display.")


# ══════════════════════════════════════════════════════════════════════════════
# Tab 2: Strategy ② AMM Reverse Swap + Multi-pool Split
# ══════════════════════════════════════════════════════════════════════════════
with tab2:
    st.subheader("Strategy ② : AMM Reverse Swap — Single Pool vs Aggregator Split")

    with st.expander("📖 Strategy Description"):
        st.markdown("""
        **Core Idea**
        When a pool becomes imbalanced during a depeg, buy the cheap token from the same pool
        and profit when the peg recovers.

        **Role of the Aggregator**
        - Routing the entire order through a single pool causes price impact (your trade moves the price)
        - An aggregator uses split routing across multiple pools to minimize slippage
        - Result: more tokens received for the same input amount
        """)

    col1, col2 = st.columns([1, 3])
    with col1:
        hour_steps = st.slider(
            "Event Progression Steps",
            min_value=5, max_value=30, value=15,
            help="Number of time steps to simulate across the event period. "
                 "e.g. 15 → compute single pool vs split difference at each step. "
                 "Higher = denser chart.",
        )
        run_s2 = st.button("▶ Run Backtest", key="run_s2", type="primary")

    if run_s2:
        with st.spinner("Running Strategy ② simulation..."):
            df2 = backtest_strategy2(event_name, amount_in=swap_amount, hour_steps=hour_steps)

        if df2.empty:
            st.error("No simulation results.")
        else:
            # Key metrics
            max_improvement = df2["improvement_usd"].max()
            avg_improvement = df2["improvement_pct"].mean()
            max_imbalance   = df2["pool_usdt_pct"].max() if "pool_usdt_pct" in df2.columns else 0

            m1, m2, m3 = st.columns(3)
            m1.metric("Max Improvement (USD)", f"${max_improvement:,.2f}",
                      help="Max additional tokens received via aggregator vs single pool")
            m2.metric("Avg Improvement %", f"{avg_improvement:.4f}%",
                      help="Average improvement rate over the full simulation period")
            m3.metric("Peak Pool Imbalance", f"{max_imbalance:.1f}%",
                      help="Highest USDT share observed during simulation")

            st.divider()

            # Single vs split output comparison chart
            fig = go.Figure()
            x_axis = df2["pool_usdt_pct"] if "pool_usdt_pct" in df2.columns else df2["hour_offset"]
            x_label = "USDT Pool Share (%)" if "pool_usdt_pct" in df2.columns else "Event Step"

            fig.add_trace(go.Scatter(
                x=x_axis, y=df2["single_out"],
                mode="lines+markers",
                name="Single Pool (Curve)",
                line=dict(color="#FF6B6B", width=2),
            ))
            fig.add_trace(go.Scatter(
                x=x_axis, y=df2["split_out"],
                mode="lines+markers",
                name="Aggregator Split",
                line=dict(color="#4ECDC4", width=2),
            ))
            fig.update_layout(
                title=f"Tokens Received on ${swap_amount:,} Swap",
                xaxis_title=x_label,
                yaxis_title="Tokens Received (USD equivalent)",
                hovermode="x unified",
                height=350,
            )
            st.plotly_chart(fig, use_container_width=True)

            # Improvement bar chart
            fig2 = go.Figure()
            fig2.add_trace(go.Bar(
                x=x_axis, y=df2["improvement_usd"],
                name="Additional Return (USD)",
                marker_color="#45B7D1",
            ))
            fig2.update_layout(
                title="Additional Return from Aggregator Split Routing",
                xaxis_title=x_label,
                yaxis_title="Additional Return (USD)",
                height=300,
            )
            st.plotly_chart(fig2, use_container_width=True)

            # Raw data table
            with st.expander("📋 Raw Data"):
                st.dataframe(df2.round(4), use_container_width=True)

    st.divider()
    st.subheader("Price Impact by Trade Size")
    st.caption("Split routing becomes more effective as trade size increases")

    if st.button("▶ Run Size Analysis", key="run_s2_size"):
        with st.spinner("Analyzing by trade size..."):
            df_size = analyze_price_impact_by_size(event_name, hour_offset=12)

        if not df_size.empty:
            fig3 = go.Figure()
            fig3.add_trace(go.Scatter(
                x=df_size["amount_in"], y=df_size["single_price_impact"],
                mode="lines", name="Single Pool Price Impact",
                line=dict(color="#FF6B6B"),
            ))
            fig3.add_trace(go.Scatter(
                x=df_size["amount_in"], y=df_size["split_price_impact"],
                mode="lines", name="Split Price Impact",
                line=dict(color="#4ECDC4"),
            ))
            fig3.update_layout(
                title="Price Impact (%) by Trade Size",
                xaxis_title="Trade Size (USD, log scale)",
                xaxis_type="log",
                yaxis_title="Price Impact (%)",
                hovermode="x unified",
                height=350,
            )
            st.plotly_chart(fig3, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# Tab 3: Strategy ③ Anticipation Position
# ══════════════════════════════════════════════════════════════════════════════
with tab3:
    st.subheader("Strategy ③ : Anticipation Position — Return by Signal Threshold")

    with st.expander("📖 Strategy Description"):
        st.markdown("""
        **Core Idea**
        When Curve 3Pool share crosses a threshold, it signals an imminent depeg.
        → Borrow the stablecoin on Aave → swap to USDC (short position)
        → Buy back at depeg lows → repay → capture spread

        **Xenophon Labs empirical finding**: Curve 3Pool share anomaly leads Chainlink oracle by **5 hours**

        **Aggregator role**: Minimize slippage on entry and exit via optimal routing
        """)

    col1, col2 = st.columns(2)
    with col1:
        thresholds_input = st.multiselect(
            "Pool Share Thresholds to Test (%)",
            options=[40, 45, 50, 55, 60, 65, 70, 75],
            default=[45, 55, 60, 65, 70],
            help="Enter short position when pool share exceeds this threshold",
        )
    with col2:
        exit_target = st.slider(
            "Exit Target Price",
            min_value=0.990, max_value=1.000, value=0.999, step=0.001,
            format="$%.3f",
        )

    if st.button("▶ Run Anticipation Backtest", key="run_s3", type="primary"):
        if not price_loaded or price_df.empty:
            st.error("No price data available. Load data from the Event Overview tab first.")
        elif not thresholds_input:
            st.warning("Select at least one threshold.")
        else:
            with st.spinner("Running Strategy ③ simulation..."):
                df3 = backtest_strategy3(
                    price_df           = price_df,
                    composition_df     = comp_df,
                    event_name         = event_name,
                    thresholds         = [float(t) for t in thresholds_input],
                    exit_target_price  = exit_target,
                )

            if df3.empty:
                st.error("No simulation results.")
            else:
                # Split by signal triggered
                triggered     = df3[df3["signal_triggered"] == True]
                not_triggered = df3[df3["signal_triggered"] == False]

                if not triggered.empty:
                    # Return bar chart
                    fig = go.Figure()
                    fig.add_trace(go.Bar(
                        x=triggered["threshold"].astype(str) + "%",
                        y=triggered["gross_pnl_pct"],
                        name="Gross Return (%)",
                        marker_color="#4ECDC4",
                    ))
                    fig.add_trace(go.Bar(
                        x=triggered["threshold"].astype(str) + "%",
                        y=-triggered["borrow_cost_pct"],
                        name="Borrow Cost (%)",
                        marker_color="#FF6B6B",
                    ))
                    fig.add_trace(go.Scatter(
                        x=triggered["threshold"].astype(str) + "%",
                        y=triggered["net_pnl_pct"],
                        mode="lines+markers",
                        name="Net Return (%)",
                        line=dict(color="#FFD93D", width=3),
                    ))
                    fig.add_hline(y=0, line_dash="dash", line_color="gray")
                    fig.update_layout(
                        title="Anticipation Position Return by Threshold",
                        xaxis_title="Pool Share Entry Threshold",
                        yaxis_title="Return (%)",
                        barmode="relative",
                        hovermode="x unified",
                        height=400,
                    )
                    st.plotly_chart(fig, use_container_width=True)

                    # Holding period chart
                    fig2 = px.bar(
                        triggered,
                        x=triggered["threshold"].astype(str) + "%",
                        y="holding_hours",
                        title="Holding Period by Threshold (hours)",
                        color="net_pnl_pct",
                        color_continuous_scale="RdYlGn",
                    )
                    st.plotly_chart(fig2, use_container_width=True)

                    # Detail table
                    st.subheader("📋 Detailed Results by Threshold")
                    display_cols = [
                        "threshold", "entry_price", "exit_price",
                        "holding_hours", "gross_pnl_pct",
                        "borrow_cost_pct", "net_pnl_pct",
                    ]
                    st.dataframe(
                        triggered[display_cols].rename(columns={
                            "threshold":       "Threshold (%)",
                            "entry_price":     "Entry Price",
                            "exit_price":      "Exit Price",
                            "holding_hours":   "Holding Hours",
                            "gross_pnl_pct":   "Gross Return (%)",
                            "borrow_cost_pct": "Borrow Cost (%)",
                            "net_pnl_pct":     "Net Return (%)",
                        }).round(4),
                        use_container_width=True,
                    )

                if not not_triggered.empty:
                    st.info(
                        f"Thresholds never triggered: "
                        f"{', '.join(not_triggered['threshold'].astype(str).tolist())}%"
                        " — pool share did not reach these levels during this event."
                    )


# ══════════════════════════════════════════════════════════════════════════════
# Tab 4: Live Curve 3Pool Monitoring
# ══════════════════════════════════════════════════════════════════════════════
with tab4:
    st.subheader("🔴 Curve 3Pool Live State")
    st.caption("Direct on-chain query from Ethereum mainnet · Contract: 0xbEbc44782C7dB0a1A60Cb6fe97d0b483032FF1C7")

    swap_size_live = st.number_input(
        "Slippage Measurement Swap Size (USD)",
        min_value=100_000,
        max_value=10_000_000,
        value=1_000_000,
        step=100_000,
        help="Measures slippage on a $1M USDT→USDC swap",
    )

    if st.button("🔄 Fetch Current State", type="primary", key="live_fetch"):
        with st.spinner("Querying Ethereum node..."):
            try:
                state = get_pool_state(pool_size_usd=swap_size_live)

                # Determine alert level
                max_pct = max(state["dai_pct"], state["usdc_pct"], state["usdt_pct"])
                if max_pct >= 75:
                    alert_level, alert_color = "🚨 CRITICAL", "error"
                elif max_pct >= 65:
                    alert_level, alert_color = "🔴 ALERT", "error"
                elif max_pct >= 50:
                    alert_level, alert_color = "🟠 WARNING", "warning"
                elif max_pct >= 40:
                    alert_level, alert_color = "🟡 WATCH", "warning"
                else:
                    alert_level, alert_color = "🟢 Normal", "success"

                # Alert banner
                if alert_color == "error":
                    st.error(f"{alert_level} — Depeg leading signal detected")
                elif alert_color == "warning":
                    st.warning(f"{alert_level} — Pool imbalance in progress")
                else:
                    st.success(f"{alert_level} — All metrics normal")

                st.divider()

                # Key metric cards
                c1, c2, c3, c4, c5 = st.columns(5)
                c1.metric("DAI Share", f"{state['dai_pct']:.2f}%",
                          delta=f"{state['dai_pct'] - 33.3:.2f}%",
                          delta_color="inverse")
                c2.metric("USDC Share", f"{state['usdc_pct']:.2f}%",
                          delta=f"{state['usdc_pct'] - 33.3:.2f}%",
                          delta_color="inverse")
                c3.metric("USDT Share", f"{state['usdt_pct']:.2f}%",
                          delta=f"{state['usdt_pct'] - 33.3:.2f}%",
                          delta_color="inverse")
                c4.metric("Virtual Price", f"{state['virtual_price']:.5f}",
                          help="Normal range: 1.00~1.07")
                c5.metric(f"Slippage (${swap_size_live/1e6:.0f}M)", f"{state['price_impact_pct']:.4f}%",
                          help=f"${swap_size_live/1e6:.0f}M USDT→USDC")

                st.divider()

                # Pool composition bar chart
                fig = go.Figure()
                tokens = ["DAI", "USDC", "USDT"]
                values = [state["dai_pct"], state["usdc_pct"], state["usdt_pct"]]
                colors = ["#F4B731", "#2775CA", "#26A17B"]

                fig.add_trace(go.Bar(
                    x=tokens, y=values,
                    marker_color=colors,
                    text=[f"{v:.2f}%" for v in values],
                    textposition="outside",
                ))
                fig.add_hline(y=33.3, line_dash="dash", line_color="gray",
                              annotation_text="Balanced (33.3%)")
                for threshold, color, label in [
                    (40, "yellow", "WATCH 40%"),
                    (65, "orange", "ALERT 65%"),
                    (75, "red",    "CRITICAL 75%"),
                ]:
                    fig.add_hline(y=threshold, line_dash="dot",
                                  line_color=color, line_width=1,
                                  annotation_text=label,
                                  annotation_font_color=color)

                fig.update_layout(
                    title="Curve 3Pool Current Token Share",
                    yaxis_title="Share (%)",
                    yaxis_range=[0, 100],
                    height=400,
                )
                st.plotly_chart(fig, use_container_width=True)

                # Additional info
                col1, col2 = st.columns(2)
                with col1:
                    st.info(f"**A (Amplification coefficient)**: {state['A']}  \nNormal: 2000. Lower = higher slippage.")
                with col2:
                    vp = state["virtual_price"]
                    vp_status = "Normal" if vp >= 1.0 else "⚠️ Abnormal"
                    st.info(f"**Virtual Price**: {vp:.6f} ({vp_status})  \nBelow 1.00 signals pool stress.")

            except Exception as e:
                st.error(f"Query failed: {e}")
                st.caption("Check that ETH_RPC_URL is set correctly in your .env file")


# ── Footer ────────────────────────────────────────────────────────────────────
st.divider()
st.caption(
    "Data sources: CoinGecko (prices) · Dune Analytics (on-chain pool composition) · "
    "StableSwap formula: Curve Finance whitepaper"
)
