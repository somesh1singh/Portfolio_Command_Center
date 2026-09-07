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

LEDGER_ALIASES = {
    "date": ["date", "posting date", "transaction date", "voucher date"],
    "description": ["particulars", "description", "narration", "remarks", "transaction details"],
    "debit": ["debit", "debit amount", "withdrawal", "dr"],
    "credit": ["credit", "credit amount", "deposit", "cr"],
    "balance": ["net balance", "closing balance", "balance", "running balance"],
}

HOLDINGS_ALIASES = {
    "symbol": ["symbol", "tradingsymbol", "trading symbol", "instrument", "security", "scrip", "scheme name", "fund name"],
    "quantity": ["quantity", "qty", "qty.", "units", "net quantity"],
    "average_cost": ["average cost", "avg. cost", "avg cost", "average price", "buy average", "invested nav"],
    "current_price": ["ltp", "last price", "current price", "closing price", "nav", "latest nav"],
    "current_value": ["current value", "cur. val", "market value", "valuation"],
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


def identify_ledger_columns(df):
    normalized = {clean_name(c): c for c in df.columns}
    result = {}
    for field, aliases in LEDGER_ALIASES.items():
        for alias in aliases:
            if clean_name(alias) in normalized:
                result[field] = normalized[clean_name(alias)]
                break
    return result


def identify_holdings_columns(df):
    normalized = {clean_name(c): c for c in df.columns}
    result = {}
    for field, aliases in HOLDINGS_ALIASES.items():
        for alias in aliases:
            if clean_name(alias) in normalized:
                result[field] = normalized[clean_name(alias)]
                break
    return result


def header_score(values):
    names = {clean_name(v) for v in values if pd.notna(v)}
    aliases = {clean_name(a) for groups in (ALIASES, LEDGER_ALIASES, HOLDINGS_ALIASES) for group in groups.values() for a in group}
    exact = len(names & aliases)
    useful = sum(any(word in name for word in ("date", "symbol", "scrip", "scheme", "quantity", "qty", "units", "price", "nav", "amount", "buy", "sell")) for name in names)
    return exact * 100 + useful * 10 + min(len(names), 9)


def excel_sheet_with_detected_header(book, sheet):
    raw = pd.read_excel(book, sheet_name=sheet, header=None, nrows=60)
    raw = raw.dropna(how="all").dropna(axis=1, how="all")
    if raw.empty:
        return None, -1
    scores = [header_score(row.tolist()) for _, row in raw.iterrows()]
    best_position = int(np.argmax(scores))
    # Re-read using the original Excel row index, which remains available after dropna.
    header_row = int(raw.index[best_position])
    frame = pd.read_excel(book, sheet_name=sheet, header=header_row)
    frame = frame.dropna(how="all").dropna(axis=1, how="all")
    return frame, scores[best_position]


def read_upload(upload):
    raw = upload.getvalue()
    if upload.name.lower().endswith((".xlsx", ".xls")):
        book = pd.ExcelFile(io.BytesIO(raw))
        candidates = []
        for sheet in book.sheet_names:
            candidate, score = excel_sheet_with_detected_header(book, sheet)
            if candidate is not None and not candidate.empty:
                candidates.append((score, sheet, candidate))
        if not candidates:
            raise ValueError("The workbook contains no non-empty worksheet.")
        candidates.sort(key=lambda item: item[0], reverse=True)
        best_score = candidates[0][0]
        # Combine sheets only when their detected structures genuinely match.
        compatible = [frame for score, _, frame in candidates if score >= 200 and list(frame.columns) == list(candidates[0][2].columns)]
        return pd.concat(compatible, ignore_index=True) if compatible else candidates[0][2]
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


def numeric_series(series):
    cleaned = series.astype(str).str.replace(",", "", regex=False).str.replace("₹", "", regex=False).str.replace(r"[^0-9.()\-]", "", regex=True)
    negative = cleaned.str.match(r"^\(.*\)$")
    values = pd.to_numeric(cleaned.str.replace("(", "", regex=False).str.replace(")", "", regex=False), errors="coerce").fillna(0.0)
    values.loc[negative] *= -1
    return values


def normalize_ledger(source, mapping):
    out = pd.DataFrame()
    out["date"] = pd.to_datetime(source[mapping["date"]], errors="coerce", dayfirst=True)
    out["description"] = source[mapping["description"]].fillna("").astype(str).str.strip()
    out["debit"] = numeric_series(source[mapping["debit"]]) if mapping.get("debit") else 0.0
    out["credit"] = numeric_series(source[mapping["credit"]]) if mapping.get("credit") else 0.0
    out["balance"] = numeric_series(source[mapping["balance"]]) if mapping.get("balance") else np.nan
    text = out["description"].str.lower()
    deposit = text.str.contains(r"funds? added|add funds|payment gateway|bank receipt|upi|neft|imps|rtgs|deposit", regex=True)
    withdrawal = text.str.contains(r"funds? withdrawn|withdrawal|payout|bank payment", regex=True)
    charges = text.str.contains(r"charge|brokerage|gst|stt|stamp|sebi|exchange fee|dp charge|interest", regex=True)
    dividend = text.str.contains(r"dividend", regex=True)
    out["category"] = np.select([deposit, withdrawal, charges, dividend], ["Deposit", "Withdrawal", "Charges/Taxes", "Dividend"], default="Other/Internal")
    # Zerodha ledger convention: money added is a credit; payout is a debit.
    out["external_cashflow"] = np.select([deposit, withdrawal], [-out["credit"].abs(), out["debit"].abs()], default=0.0)
    out = out.dropna(subset=["date"])
    out = out[(out["debit"] != 0) | (out["credit"] != 0) | (out["description"] != "")]
    return out.sort_values("date").reset_index(drop=True)


def normalize_holdings(source, mapping):
    out = pd.DataFrame()
    out["Symbol"] = source[mapping["symbol"]].astype(str).str.strip().str.upper()
    out["Quantity"] = numeric_series(source[mapping["quantity"]])
    out["Average Cost"] = numeric_series(source[mapping["average_cost"]]) if mapping.get("average_cost") else np.nan
    out["Uploaded Price"] = numeric_series(source[mapping["current_price"]]) if mapping.get("current_price") else np.nan
    current_value = numeric_series(source[mapping["current_value"]]) if mapping.get("current_value") else pd.Series(np.nan, index=source.index)
    out["Uploaded Price"] = out["Uploaded Price"].fillna((current_value / out["Quantity"]).replace([np.inf, -np.inf], np.nan))
    out = out[(out["Symbol"] != "") & (out["Symbol"] != "NAN") & (out["Quantity"] > 0)]
    out["Cost Value"] = out["Quantity"] * out["Average Cost"]
    grouped = []
    for symbol, rows in out.groupby("Symbol", sort=True):
        qty = rows["Quantity"].sum()
        cost = rows["Cost Value"].sum(min_count=1)
        valid_prices = rows["Uploaded Price"].dropna()
        grouped.append({"Symbol": symbol, "Quantity": qty, "Average Cost": cost / qty if pd.notna(cost) and qty else np.nan, "Cost Value": cost, "Uploaded Price": valid_prices.iloc[-1] if not valid_prices.empty else np.nan})
    return pd.DataFrame(grouped)


def fifo_positions(tx, actions=None):
    lots, realized = {}, {}
    events = [(row.date, 1, "trade", row) for row in tx.itertuples()]
    if actions is not None and not actions.empty:
        for record in actions.to_dict("records"):
            if pd.notna(record.get("Date")) and str(record.get("Type", "")).strip():
                events.append((pd.Timestamp(record["Date"]), 0, "action", record))
    events.sort(key=lambda item: (item[0], item[1]))

    for _, _, kind, row in events:
        if kind == "trade":
            symbol, qty, price = str(row.symbol).upper(), float(row.quantity), float(row.price)
            lots.setdefault(symbol, [])
            realized.setdefault(symbol, 0.0)
            if qty > 0:
                lots[symbol].append([qty, price])
            else:
                remaining = -qty
                while remaining > 1e-10 and lots[symbol]:
                    used = min(remaining, lots[symbol][0][0])
                    realized[symbol] += used * (price - lots[symbol][0][1])
                    lots[symbol][0][0] -= used
                    remaining -= used
                    if lots[symbol][0][0] <= 1e-10:
                        lots[symbol].pop(0)
            continue

        action = str(row.get("Type", "")).strip().lower()
        old = str(row.get("Old Symbol", "")).strip().upper()
        new = str(row.get("New Symbol", "")).strip().upper()
        numerator = float(row.get("Numerator", 1)) if pd.notna(row.get("Numerator")) and float(row.get("Numerator")) > 0 else 1.0
        denominator = float(row.get("Denominator", 1)) if pd.notna(row.get("Denominator")) and float(row.get("Denominator")) > 0 else 1.0
        factor = numerator / denominator
        allocation = float(row.get("Cost Allocation %", 0) or 0) / 100.0
        source_lots = lots.get(old, [])
        if action in ("split", "reverse split", "bonus"):
            for lot in source_lots:
                lot[0] *= factor
                lot[1] /= factor
        elif action in ("symbol change", "merger") and new and new != "NAN":
            converted = [[q * factor, p / factor] for q, p in source_lots]
            lots.setdefault(new, []).extend(converted)
            realized[new] = realized.get(new, 0.0) + realized.get(old, 0.0)
            lots[old], realized[old] = [], 0.0
        elif action == "demerger" and new and new != "NAN" and 0 <= allocation <= 1:
            child = []
            for lot in source_lots:
                original_price = lot[1]
                lot[1] = original_price * (1.0 - allocation)
                child.append([lot[0] * factor, original_price * allocation / factor])
            lots.setdefault(new, []).extend(child)
            realized.setdefault(new, 0.0)

    rows = []
    for symbol in sorted(lots):
        qty = sum(x[0] for x in lots[symbol])
        cost = sum(x[0] * x[1] for x in lots[symbol])
        if qty > 1e-10:
            rows.append({"Symbol": symbol, "Quantity": qty, "Average Cost": cost / qty, "Cost Value": cost, "Realized P&L": realized.get(symbol, 0.0)})
    return pd.DataFrame(rows), sum(realized.values())


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


@st.cache_data(ttl=86400, show_spinner=False)
def yahoo_split_actions(symbols, start, suffix):
    rows = []
    for symbol in symbols:
        ticker = symbol if any(x in symbol for x in [".", "^", "="]) else symbol + suffix
        try:
            splits = yf.Ticker(ticker).splits
            for when, ratio in splits.items():
                event_date = pd.Timestamp(when).tz_localize(None)
                if event_date.date() >= start and float(ratio) > 0:
                    rows.append({"Date": event_date.date(), "Type": "Split", "Old Symbol": symbol, "New Symbol": "", "Numerator": float(ratio), "Denominator": 1.0, "Cost Allocation %": 0.0, "Source/Notes": "Yahoo candidate — verify with NSE/company notice"})
        except Exception:
            continue
    return pd.DataFrame(rows)


def money(value):
    return f"₹{value:,.2f}"


st.title("📊 Portfolio Command Center")
st.caption("Ledger-first portfolio analytics — no Zerodha login or API connection required")

with st.sidebar:
    st.header("1. Upload portfolio files")
    trade_upload = st.file_uploader("A. Tradebook (required)", type=["csv", "xlsx", "xls"], key="tradebook", help="Used for quantities, FIFO lots, purchase prices and P&L.")
    ledger_upload = st.file_uploader("B. Funds ledger statement", type=["csv", "xlsx", "xls"], key="funds_ledger", help="Used for deposits, withdrawals, charges, dividends and account cash flows.")
    holdings_upload = st.file_uploader("C. Current holdings (recommended)", type=["csv", "xlsx", "xls"], key="holdings", help="Authoritative current quantities and average costs; used to reconcile the tradebook.")
    st.info("All three files are parsed separately and processed only in this running session. No Zerodha login is required.")
    st.header("Optional settings")
    suffix = st.text_input("Yahoo suffix for Indian securities", value=".NS", help="Use .BO for BSE securities.")
    benchmark = st.selectbox("Benchmark", ["NIFTY 50 (^NSEI)", "Gold (GC=F)", "NIFTY 500 (^CRSLDX)"])

if not trade_upload:
    st.subheader("Start with your tradebook, funds ledger, and current holdings")
    st.write("Upload the tradebook in field A. Add the funds ledger in field B for cash-flow analysis, and current holdings in field C for an authoritative present-day portfolio snapshot and reconciliation.")
    st.markdown("**Minimum columns:** Date, Symbol/Scheme, Quantity/Units, and Price/NAV. A Buy/Sell column is recommended; alternatively, use negative quantities for sells/redemptions.")
    st.stop()

try:
    source = read_upload(trade_upload)
except Exception as exc:
    st.error(f"Could not read the tradebook: {exc}")
    st.stop()

detected = identify_columns(source)
st.subheader("2. Confirm tradebook columns")
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
except Exception as exc:
    st.error(f"Could not normalize the transactions: {exc}")
    st.stop()

if tx.empty:
    st.error("No valid transactions remained after parsing. Check the selected columns and date format.")
    st.stop()

st.subheader("3. Corporate actions")
st.caption("Add or verify actions before holdings are reconstructed. Ratios are expressed as new shares ÷ old shares (for example, a 2-for-1 split is 2/1 and a 1-for-1 bonus is 2/1 total post-bonus shares).")
auto_actions = pd.DataFrame()
if st.checkbox("Check Yahoo Finance for split/bonus ratio candidates", value=False):
    with st.spinner("Checking corporate-action candidates..."):
        auto_actions = yahoo_split_actions(sorted(tx["symbol"].unique().tolist()), tx["date"].min().date(), suffix)
    st.caption("Yahoo candidates are not authoritative. Verify dates and ratios against NSE/BSE or the company announcement before using them.")
action_columns = ["Date", "Type", "Old Symbol", "New Symbol", "Numerator", "Denominator", "Cost Allocation %", "Source/Notes"]
blank_action = pd.DataFrame(columns=action_columns)
action_seed = auto_actions.reindex(columns=action_columns) if not auto_actions.empty else blank_action
actions = st.data_editor(
    action_seed,
    num_rows="dynamic",
    hide_index=True,
    use_container_width=True,
    key="corporate_actions",
    column_config={
        "Date": st.column_config.DateColumn(format="DD-MM-YYYY"),
        "Type": st.column_config.SelectboxColumn(options=["Split", "Reverse Split", "Bonus", "Demerger", "Merger", "Symbol Change"]),
        "Numerator": st.column_config.NumberColumn(min_value=0.000001, default=1.0),
        "Denominator": st.column_config.NumberColumn(min_value=0.000001, default=1.0),
        "Cost Allocation %": st.column_config.NumberColumn(min_value=0.0, max_value=100.0, default=0.0),
    },
)
actions = actions.dropna(how="all")
if not actions.empty:
    invalid_demerger = actions["Type"].astype(str).str.lower().eq("demerger") & (pd.to_numeric(actions["Cost Allocation %"], errors="coerce").fillna(0) <= 0)
    if invalid_demerger.any():
        st.error("Every demerger needs the official cost allocation percentage assigned to the new company.")
        st.stop()
try:
    positions, realized_total = fifo_positions(tx, actions)
    trade_positions = positions.copy()
except Exception as exc:
    st.error(f"Corporate-action processing failed. Check dates, ratios, and allocation percentages: {exc}")
    st.stop()

ledger_df = pd.DataFrame()
if ledger_upload:
    st.subheader("4. Confirm funds-ledger columns")
    try:
        ledger_source = read_upload(ledger_upload)
        ledger_detected = identify_ledger_columns(ledger_source)
        ledger_options = ["— Not available —"] + list(ledger_source.columns)
        ledger_mapping = {}
        ledger_cols = st.columns(5)
        for i, field in enumerate(["date", "description", "debit", "credit", "balance"]):
            default = ledger_detected.get(field, ledger_options[0])
            ledger_mapping[field] = ledger_cols[i].selectbox(field.title(), ledger_options, index=ledger_options.index(default), key=f"ledger_map_{field}")
            if ledger_mapping[field] == ledger_options[0]:
                ledger_mapping[field] = None
        if not ledger_mapping["date"] or not ledger_mapping["description"] or (not ledger_mapping["debit"] and not ledger_mapping["credit"]):
            st.warning("For ledger analysis, select Date, Description/Particulars, and at least one of Debit or Credit. Tradebook calculations remain available below.")
            with st.expander("Preview funds ledger"):
                st.dataframe(ledger_source.head(30), use_container_width=True)
        else:
            ledger_df = normalize_ledger(ledger_source, ledger_mapping)
            st.success(f"Funds ledger loaded: {len(ledger_df):,} entries. Review automatic categories in the Ledger tab.")
    except Exception as exc:
        st.warning(f"The tradebook can still be calculated, but the funds ledger could not be read: {exc}")

holdings_df = pd.DataFrame()
reconciliation = pd.DataFrame()
if holdings_upload:
    st.subheader("5. Confirm current-holdings columns")
    try:
        holdings_source = read_upload(holdings_upload)
        holdings_detected = identify_holdings_columns(holdings_source)
        holdings_options = ["— Not available —"] + list(holdings_source.columns)
        holdings_mapping = {}
        holdings_cols = st.columns(5)
        for i, field in enumerate(["symbol", "quantity", "average_cost", "current_price", "current_value"]):
            default = holdings_detected.get(field, holdings_options[0])
            holdings_mapping[field] = holdings_cols[i].selectbox(field.replace("_", " ").title(), holdings_options, index=holdings_options.index(default), key=f"holdings_map_{field}")
            if holdings_mapping[field] == holdings_options[0]:
                holdings_mapping[field] = None
        if not holdings_mapping["symbol"] or not holdings_mapping["quantity"]:
            st.warning("Select Symbol/Instrument and Quantity for the current holdings file. Average Cost and Current Price/Value are strongly recommended.")
            with st.expander("Preview current holdings"):
                st.dataframe(holdings_source.head(30), use_container_width=True)
        else:
            holdings_df = normalize_holdings(holdings_source, holdings_mapping)
            comparison = trade_positions[["Symbol", "Quantity"]].rename(columns={"Quantity": "Tradebook Quantity"}).merge(
                holdings_df[["Symbol", "Quantity"]].rename(columns={"Quantity": "Holdings Quantity"}), on="Symbol", how="outer"
            ).fillna(0)
            comparison["Difference"] = comparison["Holdings Quantity"] - comparison["Tradebook Quantity"]
            comparison["Status"] = np.where(comparison["Difference"].abs() < 1e-6, "Matched", "Review mismatch")
            reconciliation = comparison

            derived = trade_positions[["Symbol", "Average Cost", "Cost Value", "Realized P&L"]].rename(columns={"Average Cost": "Tradebook Average Cost", "Cost Value": "Tradebook Cost Value"})
            positions = holdings_df.merge(derived, on="Symbol", how="left")
            positions["Average Cost"] = positions["Average Cost"].fillna(positions["Tradebook Average Cost"])
            positions["Cost Value"] = positions["Quantity"] * positions["Average Cost"]
            positions["Realized P&L"] = positions["Realized P&L"].fillna(0.0)
            st.success(f"Current holdings loaded: {len(positions):,} securities. Uploaded quantities now drive present-day valuation.")
    except Exception as exc:
        st.warning(f"Tradebook-derived positions remain active because current holdings could not be read: {exc}")
else:
    st.warning("For the most accurate present-day picture, upload the Current Holdings file in field C. Until then, open quantities are reconstructed from the uploaded tradebook.")

if positions.empty:
    st.warning("The ledger contains no open long positions. Transaction history is shown below.")
    st.dataframe(tx, use_container_width=True)
    st.stop()

st.subheader("6. Current valuation")
st.caption("Yahoo lookup is optional. Edit any price below; calculations continue even if live data is unavailable.")
ticker_map = {s: (s if any(x in s for x in [".", "^", "="]) else s + suffix) for s in positions["Symbol"]}
prices = yahoo_prices(list(ticker_map.values()))
valuation = positions[["Symbol", "Quantity", "Average Cost", "Cost Value", "Realized P&L"]].copy()
valuation["Yahoo Ticker"] = valuation["Symbol"].map(ticker_map)
if not holdings_df.empty:
    valuation = valuation.merge(holdings_df[["Symbol", "Uploaded Price"]], on="Symbol", how="left")
else:
    valuation["Uploaded Price"] = np.nan
valuation["Current Price"] = valuation["Yahoo Ticker"].map(prices).fillna(valuation["Uploaded Price"]).fillna(valuation["Average Cost"])
valuation["Price Source"] = np.select(
    [valuation["Yahoo Ticker"].isin(prices), valuation["Uploaded Price"].notna()],
    ["Yahoo", "Current holdings file"], default="Cost fallback — edit price"
)
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

account_rate = np.nan
if not ledger_df.empty:
    external = ledger_df[ledger_df["external_cashflow"] != 0]
    if not external.empty:
        account_cashflows = external["external_cashflow"].astype(float).tolist() + [float(market_value)]
        account_dates = external["date"].dt.date.tolist() + [date.today()]
        account_rate = xirr(account_cashflows, account_dates)

k1, k2, k3, k4 = st.columns(4)
k1.metric("Current Value", money(market_value))
k2.metric("Invested Cost", money(cost_value))
k3.metric("Unrealized P&L", money(market_value - cost_value), f"{(market_value / cost_value - 1) * 100:.2f}%" if cost_value else None)
k4.metric("Portfolio XIRR", f"{portfolio_rate * 100:.2f}%" if np.isfinite(portfolio_rate) else "N/A")

if not ledger_df.empty:
    deposits = ledger_df.loc[ledger_df["category"] == "Deposit", "credit"].abs().sum()
    withdrawals = ledger_df.loc[ledger_df["category"] == "Withdrawal", "debit"].abs().sum()
    charges = ledger_df.loc[ledger_df["category"] == "Charges/Taxes", "debit"].abs().sum()
    dividends = ledger_df.loc[ledger_df["category"] == "Dividend", "credit"].abs().sum()
    l1, l2, l3, l4, l5 = st.columns(5)
    l1.metric("Funds Added", money(deposits))
    l2.metric("Funds Withdrawn", money(withdrawals))
    l3.metric("Charges/Taxes", money(charges))
    l4.metric("Dividends", money(dividends))
    l5.metric("Ledger-adjusted XIRR", f"{account_rate * 100:.2f}%" if np.isfinite(account_rate) else "N/A")
    st.caption("Ledger-adjusted XIRR uses automatically identified external deposits/withdrawals plus current securities value. Review ledger categories; opening cash and unmatched transfers can affect accuracy.")

tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs(["Holdings", "Reconciliation", "Corporate Actions", "Allocation", "Benchmarks", "Tradebook", "Funds Ledger"])
with tab1:
    display_cols = ["Symbol", "Quantity", "Average Cost", "Current Price", "Cost Value", "Market Value", "Unrealized P&L", "Realized P&L", "Return %", "Price Source"]
    st.dataframe(edited[display_cols].style.format({c: "₹{:,.2f}" for c in ["Average Cost", "Current Price", "Cost Value", "Market Value", "Unrealized P&L", "Realized P&L"]}).format({"Quantity": "{:,.4f}", "Return %": "{:.2f}%"}), use_container_width=True)
    st.download_button("Download holdings CSV", edited[display_cols].to_csv(index=False).encode(), "portfolio_holdings.csv", "text/csv")
with tab2:
    if reconciliation.empty:
        st.info("Upload Current Holdings to compare actual quantities with quantities reconstructed from the tradebook.")
    else:
        mismatches = int((reconciliation["Status"] != "Matched").sum())
        st.metric("Quantity mismatches requiring review", mismatches)
        st.dataframe(reconciliation, use_container_width=True)
        st.caption("Common causes include an incomplete tradebook period, transferred securities, bonuses, splits, mergers, or symbol changes. Current Holdings remains authoritative for today's valuation.")
with tab3:
    if actions.empty:
        st.info("No corporate actions were applied. Add verified actions in the Corporate Actions editor above when applicable.")
    else:
        st.dataframe(actions, use_container_width=True)
        st.download_button("Download applied corporate actions", actions.to_csv(index=False).encode(), "applied_corporate_actions.csv", "text/csv")
    st.markdown("**Treatment:** splits and bonuses preserve total cost; reverse splits change units at the specified ratio; mergers/symbol changes transfer lots; demergers allocate original cost between parent and child using the official percentage.")
with tab4:
    fig = px.treemap(edited, path=["Symbol"], values="Market Value", color="Return %", color_continuous_scale="RdYlGn", title="Portfolio allocation and returns")
    st.plotly_chart(fig, use_container_width=True)
with tab5:
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
with tab6:
    st.dataframe(tx, use_container_width=True)
    st.download_button("Download normalized transactions", tx.to_csv(index=False).encode(), "normalized_transactions.csv", "text/csv")
with tab7:
    if ledger_df.empty:
        st.info("Upload and map the separate funds ledger statement to see deposits, withdrawals, charges, dividends, and account cash flows.")
    else:
        st.dataframe(ledger_df, use_container_width=True)
        category_summary = ledger_df.groupby("category", as_index=False).agg(Entries=("date", "size"), Debit=("debit", "sum"), Credit=("credit", "sum"))
        st.plotly_chart(px.bar(category_summary, x="category", y=["Debit", "Credit"], barmode="group", title="Funds-ledger classification"), use_container_width=True)
        st.download_button("Download normalized funds ledger", ledger_df.to_csv(index=False).encode(), "normalized_funds_ledger.csv", "text/csv")

st.caption("Market information may be delayed or unavailable. Verify important values independently; this dashboard is not investment advice.")
