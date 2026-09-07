from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from portfolio.analytics import build_positions, portfolio_xirr
from portfolio.ledger import demo_ledger, read_ledger
from portfolio.market import fetch_yahoo, fetch_zerodha_quotes


st.set_page_config(page_title="Portfolio Command Center", page_icon="📈", layout="wide")
st.title("Portfolio Command Center")
st.caption("No broker connection required • ledger-first analytics • Yahoo verification • dynamic XIRR")


@st.cache_data(ttl=900, show_spinner=False)
def cached_market(symbols: tuple[tuple[str, str], ...], period: str):
    return fetch_yahoo(dict(symbols), period)


with st.sidebar:
    st.header("Portfolio input")
    uploaded = st.file_uploader("Upload ledger", type=["csv", "xlsx", "xls"], help="Zerodha tradebook or a generic transaction ledger")
    use_demo = st.toggle("Use demo data", value=uploaded is None)
    period = st.selectbox("Chart history", ["6mo", "1y", "2y", "5y"], index=1)
    benchmark = st.selectbox("Benchmark", ["^NSEI", "^BSESN"], format_func=lambda x: "NIFTY 50" if x == "^NSEI" else "SENSEX")
    st.divider()
    st.success("Zerodha login is not required. Your uploaded ledger is calculated locally in this app.")
    st.caption("Data refreshes every 15 minutes. Market prices may be delayed.")

try:
    if uploaded:
        ledger = read_ledger(uploaded, uploaded.name)
    elif use_demo:
        ledger = demo_ledger()
    else:
        st.info("Upload a ledger or enable demo data to begin.")
        st.stop()
except Exception as exc:
    st.error(f"Could not parse ledger: {exc}")
    st.stop()

exchanges = ledger.groupby("symbol")["exchange"].last().to_dict()
try:
    with st.spinner("Verifying market prices…"):
        prices, history, verification = cached_market(tuple(sorted(exchanges.items())), period)
except Exception as exc:
    st.warning(f"Live verification is temporarily unavailable ({exc}). Cost prices are used as fallback.")
    prices, history, verification = {}, pd.DataFrame(), pd.DataFrame()

# Keep valuation fully usable without any external connection. Yahoo values are
# prefilled when available; otherwise the latest ledger trade price is used.
fallback_prices = ledger.groupby("symbol").tail(1).set_index("symbol")["price"].to_dict()
price_rows = pd.DataFrame({
    "symbol": sorted(exchanges),
    "valuation_price": [prices.get(s) if np.isfinite(prices.get(s, np.nan)) else fallback_prices[s] for s in sorted(exchanges)],
})
with st.sidebar.expander("Review / override prices"):
    edited_prices = st.data_editor(
        price_rows,
        hide_index=True,
        disabled=["symbol"],
        column_config={"valuation_price": st.column_config.NumberColumn("Price (₹)", min_value=0.0, format="₹%.2f")},
        use_container_width=True,
    )
    st.caption("Used for today's valuation and terminal XIRR cash flow.")
prices = dict(zip(edited_prices["symbol"], edited_prices["valuation_price"]))

zerodha_prices = {}
try:
    z = st.secrets.get("zerodha", {})
    if z.get("api_key") and z.get("access_token"):
        zerodha_prices = fetch_zerodha_quotes(list(exchanges), z["api_key"], z["access_token"])
except Exception:
    st.sidebar.warning("Zerodha verification unavailable; check the daily access token.")

positions = build_positions(ledger, prices)
positions = positions.loc[positions["quantity"].abs() > 1e-10].copy()
total_value = positions["market_value"].sum()
invested = positions["invested"].sum()
unrealized = positions["unrealized_pnl"].sum()
realized = build_positions(ledger, prices)["realized_pnl"].sum()
rate = portfolio_xirr(ledger, positions)

cols = st.columns(5)
cols[0].metric("Market value", f"₹{total_value:,.0f}")
cols[1].metric("Open cost", f"₹{invested:,.0f}")
cols[2].metric("Unrealized P&L", f"₹{unrealized:,.0f}", f"{unrealized/invested:.1%}" if invested else None)
cols[3].metric("Realized P&L", f"₹{realized:,.0f}")
cols[4].metric("Portfolio XIRR", "N/A" if rate is None else f"{rate:.2%}")

overview, holdings_tab, cashflow_tab, quality_tab = st.tabs(["Overview", "Holdings", "Transactions & XIRR", "Data quality"])

with overview:
    left, right = st.columns(2)
    with left:
        if not positions.empty:
            fig = px.sunburst(positions, path=["symbol"], values="market_value", color="return_pct",
                              color_continuous_scale="RdYlGn", color_continuous_midpoint=0, title="Current allocation and return")
            fig.update_layout(margin=dict(t=45, l=10, r=10, b=10))
            st.plotly_chart(fig, use_container_width=True)
    with right:
        if not positions.empty:
            pnl = positions.sort_values("unrealized_pnl")
            fig = px.bar(pnl, x="unrealized_pnl", y="symbol", orientation="h", color="unrealized_pnl",
                         color_continuous_scale="RdYlGn", color_continuous_midpoint=0, title="Unrealized P&L by holding")
            fig.update_layout(showlegend=False, xaxis_title="P&L (₹)", yaxis_title="")
            st.plotly_chart(fig, use_container_width=True)
    if not history.empty:
        weights = positions.set_index("symbol")["market_value"]
        usable = [c for c in history.columns if c in weights.index and history[c].notna().any()]
        if usable:
            normalized = history[usable].ffill().dropna(how="all")
            normalized = normalized / normalized.apply(lambda s: s.dropna().iloc[0])
            weighted = normalized.mul(weights[usable] / weights[usable].sum()).sum(axis=1) * 100
            try:
                _, bench_hist, _ = cached_market(((benchmark, "NSE"),), period)
                bench = bench_hist[benchmark].dropna()
                bench = bench / bench.iloc[0] * 100
            except Exception:
                bench = pd.Series(dtype=float)
            fig = go.Figure(go.Scatter(x=weighted.index, y=weighted, name="Current holdings mix"))
            if not bench.empty:
                fig.add_trace(go.Scatter(x=bench.index, y=bench, name="Benchmark"))
            fig.update_layout(title="Normalized price performance (current weights; not a backtest)", yaxis_title="Index = 100", hovermode="x unified")
            st.plotly_chart(fig, use_container_width=True)

with holdings_tab:
    shown = positions.copy()
    shown["allocation"] = shown["market_value"] / total_value if total_value else 0
    if zerodha_prices:
        shown["zerodha_price"] = shown["symbol"].map(zerodha_prices)
        shown["price_variance"] = shown["zerodha_price"] / shown["last_price"] - 1
    st.dataframe(shown, use_container_width=True, hide_index=True, column_config={
        "avg_cost": st.column_config.NumberColumn(format="₹%.2f"), "last_price": st.column_config.NumberColumn(format="₹%.2f"),
        "invested": st.column_config.NumberColumn(format="₹%.0f"), "market_value": st.column_config.NumberColumn(format="₹%.0f"),
        "unrealized_pnl": st.column_config.NumberColumn(format="₹%.0f"), "realized_pnl": st.column_config.NumberColumn(format="₹%.0f"),
        "return_pct": st.column_config.NumberColumn(format="%.2f%%"), "xirr": st.column_config.NumberColumn(format="%.2f%%"),
        "allocation": st.column_config.ProgressColumn(format="%.1f%%", min_value=0, max_value=1),
    })

with cashflow_tab:
    st.subheader("Normalized transaction ledger")
    st.dataframe(ledger, use_container_width=True, hide_index=True)
    st.download_button("Download normalized CSV", ledger.to_csv(index=False).encode(), "normalized_ledger.csv", "text/csv")
    st.caption("XIRR uses actual dated buy/sell cash flows, includes charges, and values remaining holdings today.")

with quality_tab:
    if verification.empty:
        st.warning("No provider verification records are available.")
    else:
        st.dataframe(verification, use_container_width=True, hide_index=True)
        stale = verification[verification["status"] != "OK"]
        if not stale.empty:
            st.warning("Review stale or missing symbols. NSE equities normally need Yahoo's `.NS` suffix; BSE uses `.BO`.")
    oversold = []
    for symbol, group in ledger.groupby("symbol"):
        net = (group["quantity"] * group["side"].map({"BUY": 1, "SELL": -1})).cumsum()
        if (net < -1e-10).any():
            oversold.append(symbol)
    if oversold:
        st.error(f"Sell quantity exceeds prior buys for: {', '.join(oversold)}. FIFO cost/P&L requires correction.")
    else:
        st.success("Ledger sequence passed the basic quantity consistency check.")

st.caption("For personal analysis only—not investment advice. Validate broker records, corporate actions, taxes and execution prices independently.")
