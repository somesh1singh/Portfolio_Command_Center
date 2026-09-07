from __future__ import annotations

import io
from datetime import date, datetime

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf


st.set_page_config(page_title="Portfolio Command Center", page_icon="📊", layout="wide")

ALIASES = {
    "date": ["date", "trade date", "trade_date", "transaction date", "order execution time", "timestamp"],
    "symbol": ["symbol", "tradingsymbol", "trading symbol", "security", "scrip", "instrument", "scheme name", "fund name"],
    "type": ["type", "transaction type", "trade type", "buy/sell", "action", "transaction_type"],
    "quantity": ["quantity", "qty", "units", "filled quantity", "filled_quantity"],
    "price": ["price", "average price", "average_price", "rate", "nav", "trade price"],
    "amount": ["amount", "net amount", "net_amount", "value", "transaction amount"],
}


def clean_name(value):
    return " ".join(str(value).strip().lower().replace("_", " ").split())


def identify_columns(df):
    normalized = {clean_name(c): c for c in df.columns}
    result = {}
    for field, aliases in ALIASES.items():
        for alias in aliases:
            if clean_name(alias) in normalized:
                result[field] = normalized[clean_name(alias)]
                break
    return result


def read_upload(upload):
    raw = upload.getvalue()
    if upload.name.lower().endswith((".xlsx", ".xls")):
        book = pd.ExcelFile(io.BytesIO(raw))
        frames = []
        for sheet in book.sheet_names:
            candidate = pd.read_excel(book, sheet_name=sheet)
            if len(identify_columns(candidate)) >= 3:
                frames.append(candidate)
        if not frames:
            raise ValueError("No worksheet contains recognizable transaction columns.")
        return pd.concat(frames, ignore_index=True)
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return pd.read_csv(io.BytesIO(raw), encoding=encoding, sep=None, engine="python")
        except (UnicodeDecodeError, pd.errors.ParserError):
            pass
    raise ValueError("The CSV encoding or delimiter could not be recognized.")


def normalize_transactions(source, mapping):
    out = pd.DataFrame()
    out["date"] = pd.to_datetime(source[mapping["date"]], errors="coerce", dayfirst=True)
    out["symbol"] = source[mapping["symbol"]].astype(str).str.strip().str.upper()
    out["quantity"] = pd.to_numeric(source[mapping["quantity"]], errors="coerce")
    out["price"] = pd.to_numeric(source[mapping["price"]], errors="coerce") if mapping.get("price") else np.nan
    out["amount"] = pd.to_numeric(source[mapping["amount"]], errors="coerce") if mapping.get("amount") else np.nan
    if mapping.get("type"):
        action = source[mapping["type"]].astype(str).str.upper()
        is_sell = action.str.contains("SELL|REDEM|SWITCH OUT|WITHDRAW", regex=True)
        is_buy = action.str.contains("BUY|PURCHASE|SIP|SWITCH IN|INVEST", regex=True)
        out.loc[is_sell, "quantity"] = -out.loc[is_sell, "quantity"].abs()
        out.loc[is_buy, "quantity"] = out.loc[is_buy, "quantity"].abs()
    out["price"] = out["price"].fillna((out["amount"].abs() / out["quantity"].abs()).replace([np.inf], np.nan))
    out["amount"] = out["amount"].fillna(out["quantity"].abs() * out["price"])
    out = out.dropna(subset=["date", "symbol", "quantity", "price"])
    out = out[(out.symbol != "") & (out.quantity != 0) & (out.price >= 0)].sort_values("date")
    return out.reset_index(drop=True)


def fifo_positions(tx):
    rows = []
    realized_total = 0.0
    for symbol, trades in tx.groupby("symbol", sort=True):
        lots = []
        realized = 0.0
        for trade in trades.itertuples():
            qty, price = float(trade.quantity), float(trade.price)
            if qty > 0:
                lots.append([qty, price])
            else:
                remaining = -qty
                while remaining > 1e-10 and lots:
                    used = min(remaining, lots[0][0])
                    realized += used * (price - lots[0][1])
                    lots[0][0] -= used
                    remaining -= used
                    if lots[0][0] <= 1e-10:
                        lots.pop(0)
        qty = sum(x[0] for x in lots)
        cost = sum(x[0] * x[1] for x in lots)
        if qty > 1e-10:
            rows.append({"Symbol": symbol, "Quantity": qty, "Average Cost": cost / qty, "Cost Value": cost, "Realized P&L": realized})
        realized_total += realized
    return pd.DataFrame(rows), realized_total


def npv(rate, amounts, dates):
    base = dates[0]
    return sum(a / ((1.0 + rate) ** ((d - base).days / 365.0)) for a, d in zip(amounts, dates))


def xirr(amounts, dates):
    pairs = sorted((d, float(a)) for a, d in zip(amounts, dates) if pd.notna(d) and np.isfinite(a))
    if not pairs or not any(a < 0 for _, a in pairs) or not any(a > 0 for _, a in pairs):
        return np.nan
    dates2, amounts2 = zip(*pairs)
    low, high = -0.9999, 10.0
    f_low, f_high = npv(low, amounts2, dates2), npv(high, amounts2, dates2)
    while f_low * f_high > 0 and high < 1e6:
        high *= 10
        f_high = npv(high, amounts2, dates2)
    if f_low * f_high > 0:
        return np.nan
    for _ in range(200):
        mid = (low + high) / 2
        f_mid = npv(mid, amounts2, dates2)
        if abs(f_mid) < 1e-7:
            return mid
        if f_low * f_mid <= 0:
            high = mid
        else:
            low, f_low = mid, f_mid
    return (low + high) / 2


@st.cache_data(ttl=900, show_spinner=False)
def yahoo_prices(tickers):
    result = {}
    for ticker in tickers:
        try:
            hist = yf.Ticker(ticker).history(period="5d", auto_adjust=False)
            if not hist.empty:
                result[ticker] = float(hist["Close"].dropna().iloc[-1])
        except Exception:
            continue
    return result


@st.cache_data(ttl=3600, show_spinner=False)
def benchmark_series(ticker, start):
    try:
        data = yf.download(ticker, start=start, end=date.today(), progress=False, auto_adjust=True)
        close = data["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        return close.dropna()
    except Exception:
        return pd.Series(dtype=float)


def money(value):
    return f"₹{value:,.2f}"


st.title("📊 Portfolio Command Center")
st.caption("Ledger-first portfolio analytics — no Zerodha login or API connection required")

with st.sidebar:
    st.header("1. Upload ledger")
    upload = st.file_uploader("CSV or Excel trade ledger", type=["csv", "xlsx", "xls"])
    st.info("Your ledger is processed only in this running session.")
    st.header("Optional settings")
    suffix = st.text_input("Yahoo suffix for Indian securities", value=".NS", help="Use .BO for BSE securities.")
    benchmark = st.selectbox("Benchmark", ["NIFTY 50 (^NSEI)", "Gold (GC=F)", "NIFTY 500 (^CRSLDX)"])

if not upload:
    st.subheader("Start with your existing broker or mutual-fund ledger")
    st.write("Upload the actual CSV/XLSX file. The app reconstructs open positions using FIFO, calculates realized and unrealized P&L, and computes cash-flow-correct XIRR.")
    st.markdown("**Minimum columns:** Date, Symbol/Scheme, Quantity/Units, and Price/NAV. A Buy/Sell column is recommended; alternatively, use negative quantities for sells/redemptions.")
    st.stop()

try:
    source = read_upload(upload)
except Exception as exc:
    st.error(f"Could not read the ledger: {exc}")
    st.stop()

detected = identify_columns(source)
st.subheader("2. Confirm ledger columns")
options = ["— Not available —"] + list(source.columns)
cols = st.columns(6)
mapping = {}
for i, field in enumerate(["date", "symbol", "type", "quantity", "price", "amount"]):
    default = detected.get(field, options[0])
    mapping[field] = cols[i].selectbox(field.title(), options, index=options.index(default), key=f"map_{field}")
    if mapping[field] == options[0]:
        mapping[field] = None

required = ["date", "symbol", "quantity"]
if any(not mapping[x] for x in required) or (not mapping["price"] and not mapping["amount"]):
    st.warning("Select Date, Symbol, Quantity, and either Price or Amount.")
    st.dataframe(source.head(20), use_container_width=True)
    st.stop()

try:
    tx = normalize_transactions(source, mapping)
    positions, realized_total = fifo_positions(tx)
except Exception as exc:
    st.error(f"Could not normalize the transactions: {exc}")
    st.stop()

if tx.empty:
    st.error("No valid transactions remained after parsing. Check the selected columns and date format.")
    st.stop()

if positions.empty:
    st.warning("The ledger contains no open long positions. Transaction history is shown below.")
    st.dataframe(tx, use_container_width=True)
    st.stop()

st.subheader("3. Current valuation")
st.caption("Yahoo lookup is optional. Edit any price below; calculations continue even if live data is unavailable.")
ticker_map = {s: (s if any(x in s for x in [".", "^", "="]) else s + suffix) for s in positions["Symbol"]}
prices = yahoo_prices(list(ticker_map.values()))
valuation = positions[["Symbol", "Quantity", "Average Cost", "Cost Value", "Realized P&L"]].copy()
valuation["Yahoo Ticker"] = valuation["Symbol"].map(ticker_map)
valuation["Current Price"] = valuation["Yahoo Ticker"].map(prices).fillna(valuation["Average Cost"])
valuation["Price Source"] = np.where(valuation["Yahoo Ticker"].isin(prices), "Yahoo", "Cost fallback — edit price")
edited = st.data_editor(valuation, hide_index=True, use_container_width=True, disabled=["Symbol", "Quantity", "Average Cost", "Cost Value", "Realized P&L", "Price Source"], column_config={"Current Price": st.column_config.NumberColumn(min_value=0.0, format="₹%.2f")})
edited["Market Value"] = edited["Quantity"] * edited["Current Price"]
edited["Unrealized P&L"] = edited["Market Value"] - edited["Cost Value"]
edited["Return %"] = np.where(edited["Cost Value"] != 0, edited["Unrealized P&L"] / edited["Cost Value"] * 100, np.nan)

market_value = edited["Market Value"].sum()
cost_value = edited["Cost Value"].sum()
cashflows = []
cf_dates = []
for row in tx.itertuples():
    cashflows.append(-float(row.quantity) * float(row.price))
    cf_dates.append(row.date.date())
cashflows.append(float(market_value))
cf_dates.append(date.today())
portfolio_rate = xirr(cashflows, cf_dates)

k1, k2, k3, k4 = st.columns(4)
k1.metric("Current Value", money(market_value))
k2.metric("Invested Cost", money(cost_value))
k3.metric("Unrealized P&L", money(market_value - cost_value), f"{(market_value / cost_value - 1) * 100:.2f}%" if cost_value else None)
k4.metric("Portfolio XIRR", f"{portfolio_rate * 100:.2f}%" if np.isfinite(portfolio_rate) else "N/A")

tab1, tab2, tab3, tab4 = st.tabs(["Holdings", "Allocation", "Benchmarks", "Transactions"])
with tab1:
    display_cols = ["Symbol", "Quantity", "Average Cost", "Current Price", "Cost Value", "Market Value", "Unrealized P&L", "Realized P&L", "Return %", "Price Source"]
    st.dataframe(edited[display_cols].style.format({c: "₹{:,.2f}" for c in ["Average Cost", "Current Price", "Cost Value", "Market Value", "Unrealized P&L", "Realized P&L"]}).format({"Quantity": "{:,.4f}", "Return %": "{:.2f}%"}), use_container_width=True)
    st.download_button("Download holdings CSV", edited[display_cols].to_csv(index=False).encode(), "portfolio_holdings.csv", "text/csv")
with tab2:
    fig = px.treemap(edited, path=["Symbol"], values="Market Value", color="Return %", color_continuous_scale="RdYlGn", title="Portfolio allocation and returns")
    st.plotly_chart(fig, use_container_width=True)
with tab3:
    bench_ticker = {"NIFTY 50 (^NSEI)": "^NSEI", "Gold (GC=F)": "GC=F", "NIFTY 500 (^CRSLDX)": "^CRSLDX"}[benchmark]
    series = benchmark_series(bench_ticker, tx["date"].min().date())
    if series.empty:
        st.warning("Benchmark data is temporarily unavailable from Yahoo Finance.")
    else:
        normalized = series / series.iloc[0] * 100
        fig = go.Figure(go.Scatter(x=normalized.index, y=normalized, name=benchmark))
        fig.update_layout(title="Benchmark growth of 100", yaxis_title="Indexed value", hovermode="x unified")
        st.plotly_chart(fig, use_container_width=True)
        years = max((series.index[-1].date() - series.index[0].date()).days / 365.0, 1 / 365)
        bench_cagr = (series.iloc[-1] / series.iloc[0]) ** (1 / years) - 1
        st.metric(f"{benchmark} CAGR over ledger period", f"{bench_cagr * 100:.2f}%")
        st.caption("Benchmark CAGR is a time-period reference, not a cash-flow-matched benchmark XIRR.")
with tab4:
    st.dataframe(tx, use_container_width=True)
    st.download_button("Download normalized transactions", tx.to_csv(index=False).encode(), "normalized_transactions.csv", "text/csv")

st.caption("Market information may be delayed or unavailable. Verify important values independently; this dashboard is not investment advice.")
