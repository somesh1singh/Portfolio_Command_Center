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
    "voucher_type": ["voucher type", "voucher", "entry type"],
}

HOLDINGS_ALIASES = {
    "symbol": ["symbol", "tradingsymbol", "trading symbol", "instrument", "security", "scrip", "scheme name", "fund name"],
    "quantity": ["quantity", "quantity available", "qty", "qty.", "units", "net quantity"],
    "average_cost": ["average cost", "avg. cost", "avg cost", "average price", "buy average", "invested nav"],
    "current_price": ["ltp", "last price", "current price", "closing price", "previous closing price", "nav", "latest nav"],
    "current_value": ["current value", "cur. val", "market value", "valuation"],
}


def clean_name(value):
    return " ".join(str(value).strip().lower().replace("_", " ").split())


def parse_dates(series):
    """Parse ISO, Indian day-first, Excel datetime, and mixed date columns safely."""
    return pd.to_datetime(series, errors="coerce", format="mixed", dayfirst=True)


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


def read_holdings_upload(upload):
    """Combine every recognizable holdings worksheet into one canonical table."""
    if not upload.name.lower().endswith((".xlsx", ".xls")):
        return read_upload(upload)
    book = pd.ExcelFile(io.BytesIO(upload.getvalue()))
    frames = []
    for sheet in book.sheet_names:
        candidate, _ = excel_sheet_with_detected_header(book, sheet)
        if candidate is None or candidate.empty:
            continue
        found = identify_holdings_columns(candidate)
        if not found.get("symbol") or not found.get("quantity"):
            continue
        canonical = pd.DataFrame({
            "Symbol": candidate[found["symbol"]],
            "Quantity": candidate[found["quantity"]],
            "Average Cost": candidate[found["average_cost"]] if found.get("average_cost") else np.nan,
            "Current Price": candidate[found["current_price"]] if found.get("current_price") else np.nan,
            "Current Value": candidate[found["current_value"]] if found.get("current_value") else np.nan,
            "Asset Class": "Mutual Fund" if "mutual" in sheet.lower() else "Equity",
            "Sector": candidate["Sector"] if "Sector" in candidate else (candidate["Instrument Type"] if "Instrument Type" in candidate else "Unclassified"),
            "ISIN": candidate["ISIN"] if "ISIN" in candidate else "",
        })
        # Broker statements often provide price but not an explicit current-value column.
        q = numeric_series(canonical["Quantity"])
        px = numeric_series_with_blanks(canonical["Current Price"])
        explicit = numeric_series_with_blanks(canonical["Current Value"])
        canonical["Current Value"] = explicit.fillna(q * px)
        frames.append(canonical)
    if not frames:
        return read_upload(upload)
    return pd.concat(frames, ignore_index=True)


def normalize_transactions(source, mapping):
    out = pd.DataFrame()
    out["date"] = parse_dates(source[mapping["date"]])
    out["symbol"] = source[mapping["symbol"]].astype(str).str.strip().str.upper()
    out["original_symbol"] = out["symbol"]
    out["isin"] = source["ISIN"].fillna("").astype(str).str.strip().str.upper() if "ISIN" in source else ""
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


def numeric_series_with_blanks(series):
    values = numeric_series(series)
    blank = series.isna() | series.astype(str).str.strip().str.lower().isin(["", "nan", "none", "-"])
    values.loc[blank] = np.nan
    return values


def normalize_ledger(source, mapping):
    out = pd.DataFrame()
    out["date"] = parse_dates(source[mapping["date"]])
    out["description"] = source[mapping["description"]].fillna("").astype(str).str.strip()
    out["debit"] = numeric_series(source[mapping["debit"]]) if mapping.get("debit") else 0.0
    out["credit"] = numeric_series(source[mapping["credit"]]) if mapping.get("credit") else 0.0
    out["balance"] = numeric_series_with_blanks(source[mapping["balance"]]) if mapping.get("balance") else np.nan
    out["voucher_type"] = source[mapping["voucher_type"]].fillna("").astype(str).str.strip() if mapping.get("voucher_type") else ""
    text = out["description"].str.lower()
    voucher = out["voucher_type"].str.lower()
    deposit = voucher.eq("bank receipts") | text.str.contains(r"funds? added|add funds|payment gateway|bank receipt|upi|neft|imps|rtgs|deposit", regex=True)
    withdrawal = voucher.eq("bank payments") | text.str.contains(r"funds? withdrawn|withdrawal|payout|bank payment|auto-settled|auto settled|transferred back|quarterly settlement", regex=True)
    charges = text.str.contains(r"charge|brokerage|gst|stt|stamp|sebi|exchange fee|dp charge|interest", regex=True)
    dividend = text.str.contains(r"dividend", regex=True)
    out["category"] = np.select([deposit, withdrawal, charges, dividend], ["Deposit", "Withdrawal", "Charges/Taxes", "Dividend"], default="Other/Internal")
    # Zerodha ledger convention: money added is a credit; payout is a debit.
    out["external_cashflow"] = np.select([deposit, withdrawal], [-out["credit"].abs(), out["debit"].abs()], default=0.0)
    out = out.dropna(subset=["date"])
    out = out[(out["debit"] != 0) | (out["credit"] != 0) | (out["description"] != "")]
    return out.sort_values("date", kind="stable").reset_index(drop=True)


def normalize_holdings(source, mapping):
    out = pd.DataFrame()
    out["Symbol"] = source[mapping["symbol"]].astype(str).str.strip().str.upper()
    out["Quantity"] = numeric_series(source[mapping["quantity"]])
    out["Average Cost"] = numeric_series_with_blanks(source[mapping["average_cost"]]).replace(0, np.nan) if mapping.get("average_cost") else np.nan
    out["Uploaded Price"] = numeric_series_with_blanks(source[mapping["current_price"]]).replace(0, np.nan) if mapping.get("current_price") else np.nan
    current_value = numeric_series_with_blanks(source[mapping["current_value"]]) if mapping.get("current_value") else pd.Series(np.nan, index=source.index)
    out["Uploaded Price"] = out["Uploaded Price"].fillna((current_value / out["Quantity"]).replace([np.inf, -np.inf], np.nan))
    out["Uploaded Market Value"] = current_value.replace(0, np.nan).fillna(out["Quantity"] * out["Uploaded Price"])
    out["Asset Class"] = source["Asset Class"].fillna("Unclassified").astype(str) if "Asset Class" in source else "Unclassified"
    out["Sector"] = source["Sector"].fillna("Unclassified").astype(str) if "Sector" in source else "Unclassified"
    out["ISIN"] = source["ISIN"].fillna("").astype(str) if "ISIN" in source else ""
    out = out[(out["Symbol"] != "") & (out["Symbol"] != "NAN") & (out["Quantity"] > 0)]
    out["Cost Value"] = out["Quantity"] * out["Average Cost"]
    grouped = []
    for symbol, rows in out.groupby("Symbol", sort=True):
        qty = rows["Quantity"].sum()
        cost = rows["Cost Value"].sum(min_count=1)
        market_value = rows["Uploaded Market Value"].sum(min_count=1)
        valid_prices = rows["Uploaded Price"].dropna()
        uploaded_price = market_value / qty if pd.notna(market_value) and qty else (valid_prices.iloc[-1] if not valid_prices.empty else np.nan)
        grouped.append({"Symbol": symbol, "Quantity": qty, "Average Cost": cost / qty if pd.notna(cost) and qty else np.nan, "Cost Value": cost, "Uploaded Price": uploaded_price, "Uploaded Market Value": market_value, "Asset Class": rows["Asset Class"].iloc[0], "Sector": rows["Sector"].iloc[0], "ISIN": rows["ISIN"].iloc[0]})
    return pd.DataFrame(grouped)


def fifo_positions(tx, actions=None):
    lots, realized = {}, {}
    closed_trades = []
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
                lots[symbol].append([qty, price, pd.Timestamp(row.date)])
            else:
                remaining = -qty
                while remaining > 1e-10 and lots[symbol]:
                    used = min(remaining, lots[symbol][0][0])
                    buy_price, buy_date = lots[symbol][0][1], lots[symbol][0][2]
                    lot_pnl = used * (price - buy_price)
                    realized[symbol] += lot_pnl
                    closed_trades.append({"Symbol": symbol, "Buy Date": buy_date, "Sell Date": pd.Timestamp(row.date), "Quantity": used, "Buy Price": buy_price, "Sell Price": price, "Invested Amount": used * buy_price, "Sale Amount": used * price, "Realized P&L": lot_pnl, "Return %": (price / buy_price - 1) * 100 if buy_price else np.nan, "Holding Days": (pd.Timestamp(row.date) - buy_date).days})
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
            converted = [[q * factor, p / factor, acquired] for q, p, acquired in source_lots]
            lots.setdefault(new, []).extend(converted)
            realized[new] = realized.get(new, 0.0) + realized.get(old, 0.0)
            lots[old], realized[old] = [], 0.0
        elif action == "demerger" and new and new != "NAN" and 0 <= allocation <= 1:
            child = []
            for lot in source_lots:
                original_price = lot[1]
                lot[1] = original_price * (1.0 - allocation)
                child.append([lot[0] * factor, original_price * allocation / factor, lot[2]])
            lots.setdefault(new, []).extend(child)
            realized.setdefault(new, 0.0)

    rows = []
    for symbol in sorted(lots):
        qty = sum(x[0] for x in lots[symbol])
        cost = sum(x[0] * x[1] for x in lots[symbol])
        if qty > 1e-10:
            weighted_days = sum(x[0] * max((pd.Timestamp(date.today()) - x[2]).days, 0) for x in lots[symbol]) / qty
            rows.append({"Symbol": symbol, "Quantity": qty, "Average Cost": cost / qty, "Cost Value": cost, "Realized P&L": realized.get(symbol, 0.0), "Oldest Open Lot": min(x[2] for x in lots[symbol]), "Weighted Holding Days": weighted_days})
    return pd.DataFrame(rows), sum(realized.values()), pd.DataFrame(closed_trades)


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
    tickers = list(dict.fromkeys(tickers))
    if not tickers:
        return result
    try:
        data = yf.download(tickers, period="5d", auto_adjust=False, progress=False, group_by="ticker", threads=True)
        if len(tickers) == 1:
            close = data["Close"].dropna()
            if not close.empty:
                result[tickers[0]] = float(close.iloc[-1])
        else:
            for ticker in tickers:
                try:
                    close = data[ticker]["Close"].dropna()
                    if not close.empty:
                        result[ticker] = float(close.iloc[-1])
                except (KeyError, TypeError):
                    continue
    except Exception:
        pass
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


@st.cache_data(ttl=3600, show_spinner=False)
def risk_price_history(tickers, benchmark_ticker, period="1y"):
    requested = list(dict.fromkeys([t for t in tickers if t] + [benchmark_ticker]))
    try:
        data = yf.download(requested, period=period, progress=False, auto_adjust=True, threads=True)
        close = data["Close"] if isinstance(data.columns, pd.MultiIndex) else data[["Close"]].rename(columns={"Close": requested[0]})
        if isinstance(close, pd.Series):
            close = close.to_frame(requested[0])
        return close.dropna(how="all")
    except Exception:
        return pd.DataFrame()


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


@st.cache_data(show_spinner=False)
def monthly_portfolio_history(tx, actions):
    if tx.empty:
        return pd.DataFrame()
    months = pd.period_range(tx["date"].min().to_period("M"), pd.Timestamp(date.today()).to_period("M"), freq="M")
    rows = []
    for month in months:
        cutoff = min(month.end_time.normalize(), pd.Timestamp(date.today()))
        subset = tx[tx["date"] <= cutoff]
        action_subset = actions[pd.to_datetime(actions["Date"], errors="coerce") <= cutoff] if actions is not None and not actions.empty else actions
        snapshot, _, _ = fifo_positions(subset, action_subset)
        rows.append({"Month": cutoff, "Year": cutoff.year, "Number of Holdings": len(snapshot), "Invested Amount": snapshot["Cost Value"].sum() if not snapshot.empty else 0.0})
    return pd.DataFrame(rows)


def money(value):
    return f"₹{value:,.2f}"


def excel_report_bytes(tables):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for name, frame in tables.items():
            safe = name[:31]
            frame.to_excel(writer, sheet_name=safe, index=False)
            ws = writer.book[safe]
            ws.freeze_panes = "A2"
            ws.auto_filter.ref = ws.dimensions
            for cell in ws[1]:
                cell.font = cell.font.copy(bold=True)
            for column in ws.columns:
                values = [str(c.value) if c.value is not None else "" for c in list(column)[:200]]
                ws.column_dimensions[column[0].column_letter].width = min(max(max(map(len, values), default=8) + 2, 10), 35)
    return output.getvalue()


def pdf_report_bytes(summary_rows, quality_report, yearly_funds, yearly_pnl):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    output = io.BytesIO()
    doc = SimpleDocTemplate(output, pagesize=landscape(A4), rightMargin=28, leftMargin=28, topMargin=28, bottomMargin=28)
    styles = getSampleStyleSheet()
    story = [Paragraph("Portfolio Command Center — Audit Report", styles["Title"]), Paragraph(f"Generated {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}", styles["Normal"]), Spacer(1, 12)]
    for title, rows in [("Executive Summary", summary_rows), ("Data Quality Checks", [quality_report.columns.tolist()] + quality_report.astype(str).values.tolist())]:
        story.append(Paragraph(title, styles["Heading2"]))
        table = Table(rows, repeatRows=1)
        table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f4e78")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("GRID", (0, 0), (-1, -1), .25, colors.grey), ("FONTSIZE", (0, 0), (-1, -1), 7), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story.extend([table, Spacer(1, 12)])
    for title, frame in [("Yearly Fund Flows", yearly_funds), ("Yearly Realized Profit", yearly_pnl)]:
        if not frame.empty:
            story.append(Paragraph(title, styles["Heading2"]))
            rows = [frame.columns.tolist()] + frame.round(2).astype(str).values.tolist()
            table = Table(rows, repeatRows=1)
            table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f4e78")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("GRID", (0, 0), (-1, -1), .25, colors.grey), ("FONTSIZE", (0, 0), (-1, -1), 7)]))
            story.extend([table, Spacer(1, 12)])
    story.append(Paragraph("Indicative analytics only. Verify corporate actions, tax treatment, classifications, and broker totals before relying on the report.", styles["Italic"]))
    doc.build(story)
    return output.getvalue()


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
    risk_free_rate = st.number_input("Risk-free rate for Sharpe (%)", min_value=0.0, max_value=25.0, value=6.5, step=0.25) / 100

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

# Resolve ticker-name changes using ISIN before FIFO processing.
preloaded_holdings_source = None
isin_symbol_changes = pd.DataFrame()
if holdings_upload:
    try:
        preloaded_holdings_source = read_holdings_upload(holdings_upload)
        if "ISIN" in preloaded_holdings_source and "isin" in tx:
            current_symbols = preloaded_holdings_source.dropna(subset=["ISIN", "Symbol"]).copy()
            current_symbols["ISIN"] = current_symbols["ISIN"].astype(str).str.strip().str.upper()
            isin_map = current_symbols.drop_duplicates("ISIN").set_index("ISIN")["Symbol"].astype(str).str.strip().str.upper().to_dict()
            mapped = tx["isin"].map(isin_map)
            changed = mapped.notna() & mapped.ne(tx["symbol"])
            isin_symbol_changes = tx.loc[changed, ["symbol", "isin"]].drop_duplicates().rename(columns={"symbol": "Old Symbol", "isin": "ISIN"})
            isin_symbol_changes["Current Symbol"] = isin_symbol_changes["ISIN"].map(isin_map)
            tx.loc[changed, "symbol"] = mapped.loc[changed]
    except Exception:
        preloaded_holdings_source = None

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
    positions, realized_total, closed_trades = fifo_positions(tx, actions)
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
        ledger_cols = st.columns(6)
        for i, field in enumerate(["date", "description", "debit", "credit", "balance", "voucher_type"]):
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
            st.success(f"Funds ledger loaded: {len(ledger_df):,} entries. Confirm automatic categories below before XIRR is calculated.")
            ledger_df = st.data_editor(
                ledger_df,
                hide_index=True,
                use_container_width=True,
                key="ledger_classification_editor",
                disabled=["date", "description", "debit", "credit", "balance", "voucher_type", "external_cashflow"],
                column_config={"category": st.column_config.SelectboxColumn(options=["Deposit", "Withdrawal", "Charges/Taxes", "Dividend", "Other/Internal"], required=True)},
            )
            ledger_df["external_cashflow"] = np.select(
                [ledger_df["category"].eq("Deposit"), ledger_df["category"].eq("Withdrawal")],
                [-ledger_df["credit"].abs(), ledger_df["debit"].abs()], default=0.0
            )
    except Exception as exc:
        st.warning(f"The tradebook can still be calculated, but the funds ledger could not be read: {exc}")

holdings_df = pd.DataFrame()
reconciliation = pd.DataFrame()
if holdings_upload:
    st.subheader("5. Confirm current-holdings columns")
    try:
        holdings_source = preloaded_holdings_source if preloaded_holdings_source is not None else read_holdings_upload(holdings_upload)
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

            derived = trade_positions[["Symbol", "Average Cost", "Cost Value", "Realized P&L", "Oldest Open Lot", "Weighted Holding Days"]].rename(columns={"Average Cost": "Tradebook Average Cost", "Cost Value": "Tradebook Cost Value"})
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
if "Asset Class" in positions:
    mutual_symbols = set(positions.loc[positions["Asset Class"].astype(str).str.lower().eq("mutual fund"), "Symbol"])
    ticker_map = {symbol: ("" if symbol in mutual_symbols else ticker) for symbol, ticker in ticker_map.items()}
prices = yahoo_prices([ticker for ticker in ticker_map.values() if ticker])
valuation_columns = [c for c in ["Symbol", "Quantity", "Average Cost", "Cost Value", "Realized P&L", "Asset Class", "Sector", "ISIN"] if c in positions.columns]
valuation = positions[valuation_columns].copy()
valuation["Yahoo Ticker"] = valuation["Symbol"].map(ticker_map)
if not holdings_df.empty:
    valuation = valuation.merge(holdings_df[["Symbol", "Uploaded Price", "Uploaded Market Value"]], on="Symbol", how="left")
else:
    valuation["Uploaded Price"] = np.nan
    valuation["Uploaded Market Value"] = np.nan
valuation["Yahoo Price"] = valuation["Yahoo Ticker"].map(prices)
# The broker holdings snapshot is authoritative; Yahoo is verification only.
valuation["Current Price"] = valuation["Uploaded Price"].fillna(valuation["Yahoo Price"]).fillna(valuation["Average Cost"])
valuation["Price Source"] = np.select(
    [valuation["Uploaded Price"].notna(), valuation["Yahoo Price"].notna()],
    ["Current holdings file", "Yahoo"], default="Cost fallback — edit price"
)
valuation["Yahoo Difference %"] = np.where(valuation["Yahoo Price"].notna() & (valuation["Current Price"] != 0), (valuation["Yahoo Price"] / valuation["Current Price"] - 1) * 100, np.nan)
edited = st.data_editor(valuation, hide_index=True, use_container_width=True, disabled=["Symbol", "Quantity", "Average Cost", "Cost Value", "Realized P&L", "Yahoo Ticker", "Uploaded Price", "Uploaded Market Value", "Yahoo Price", "Yahoo Difference %", "Price Source"], column_config={"Current Price": st.column_config.NumberColumn(min_value=0.0, format="₹%.4f"), "Yahoo Difference %": st.column_config.NumberColumn(format="%.2f%%")})
edited["Market Value"] = edited["Quantity"] * edited["Current Price"]
edited["Unrealized P&L"] = edited["Market Value"] - edited["Cost Value"]
edited["Return %"] = np.where(edited["Cost Value"] != 0, edited["Unrealized P&L"] / edited["Cost Value"] * 100, np.nan)

market_value = edited["Market Value"].sum()
cost_value = edited["Cost Value"].sum()
trade_symbols = set(tx["symbol"].astype(str).str.upper())
trade_market_value = edited.loc[edited["Symbol"].isin(trade_symbols), "Market Value"].sum()
cashflows = []
cf_dates = []
for row in tx.itertuples():
    cashflows.append(-float(row.quantity) * float(row.price))
    cf_dates.append(row.date.date())
cashflows.append(float(trade_market_value))
cf_dates.append(date.today())
portfolio_rate = xirr(cashflows, cf_dates)
trade_xirr_audit = pd.DataFrame({"Date": cf_dates, "Cash Flow": cashflows})
trade_xirr_audit["Source"] = ["Tradebook buy/sell"] * (len(trade_xirr_audit) - 1) + ["Current value of tradebook-covered securities"]

account_rate = np.nan
closing_cash = 0.0
account_xirr_audit = pd.DataFrame()
external = pd.DataFrame()
if not ledger_df.empty:
    known_balances = pd.to_numeric(ledger_df["balance"], errors="coerce").dropna()
    closing_cash = float(known_balances.iloc[-1]) if not known_balances.empty else 0.0
    external = ledger_df[ledger_df["external_cashflow"] != 0]
    if not external.empty:
        account_cashflows = external["external_cashflow"].astype(float).tolist() + [float(market_value + closing_cash)]
        account_dates = external["date"].dt.date.tolist() + [date.today()]
        account_rate = xirr(account_cashflows, account_dates)
        account_xirr_audit = pd.DataFrame({"Date": account_dates, "Cash Flow": account_cashflows})
        account_xirr_audit["Source"] = external["category"].tolist() + ["Securities value + closing cash"]

k1, k2, k3, k4 = st.columns(4)
k1.metric("Current Value", money(market_value))
k2.metric("Invested Cost", money(cost_value))
k3.metric("Unrealized P&L", money(market_value - cost_value), f"{(market_value / cost_value - 1) * 100:.2f}%" if cost_value else None)
k4.metric("Portfolio XIRR", f"{portfolio_rate * 100:.2f}%" if np.isfinite(portfolio_rate) else "N/A")

if "Asset Class" in edited.columns:
    asset_values = edited.groupby("Asset Class")["Market Value"].sum()
    ac_cols = st.columns(max(len(asset_values), 1))
    for col, (asset_class, value) in zip(ac_cols, asset_values.items()):
        col.metric(f"{asset_class} Value", money(value), f"{value / market_value * 100:.2f}%" if market_value else None)

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
    st.metric("Closing cash balance included in account XIRR", money(closing_cash))
    st.caption("Ledger-adjusted XIRR uses confirmed external deposits/withdrawals plus current securities value and the last available ledger balance. Opening assets, unmatched transfers, or a ledger ending before today can affect accuracy.")

# Comprehensive performance datasets. Stock Return % uses total realized plus current
# unrealized P&L divided by cumulative purchase value, so repeated trading is explicit.
trade_summary = tx.groupby("symbol", as_index=False).agg(
    Trades=("symbol", "size"), First_Trade=("date", "min"), Last_Trade=("date", "max")
).rename(columns={"symbol": "Symbol", "First_Trade": "First Trade", "Last_Trade": "Last Trade"})
buys = tx[tx["quantity"] > 0].assign(Purchase_Value=lambda d: d["quantity"] * d["price"]).groupby("symbol", as_index=False).agg(
    Buy_Transactions=("symbol", "size"), Purchase_Value=("Purchase_Value", "sum")
).rename(columns={"symbol": "Symbol", "Buy_Transactions": "Buy Transactions", "Purchase_Value": "Cumulative Purchase Value"})
sells = tx[tx["quantity"] < 0].groupby("symbol", as_index=False).size().rename(columns={"symbol": "Symbol", "size": "Sell Transactions"})
open_performance = edited[["Symbol", "Market Value", "Unrealized P&L", "Realized P&L", "Return %"]].copy()
stock_report = trade_summary.merge(buys, on="Symbol", how="left").merge(sells, on="Symbol", how="left").merge(open_performance, on="Symbol", how="outer")
for column in ["Trades", "Buy Transactions", "Sell Transactions", "Cumulative Purchase Value", "Market Value", "Unrealized P&L", "Realized P&L"]:
    stock_report[column] = pd.to_numeric(stock_report[column], errors="coerce").fillna(0)
stock_report["Total P&L"] = stock_report["Realized P&L"] + stock_report["Unrealized P&L"]
stock_report["Total Return on Purchases %"] = np.where(stock_report["Cumulative Purchase Value"] > 0, stock_report["Total P&L"] / stock_report["Cumulative Purchase Value"] * 100, np.nan)

holding_report = positions[[c for c in ["Symbol", "Quantity", "Oldest Open Lot", "Weighted Holding Days"] if c in positions.columns]].copy()
if "Oldest Open Lot" not in holding_report:
    holding_report["Oldest Open Lot"] = pd.NaT
if "Weighted Holding Days" not in holding_report:
    holding_report["Weighted Holding Days"] = np.nan

monthly_profit = pd.DataFrame()
yearly_profit = pd.DataFrame()
if not closed_trades.empty:
    sell_dates = pd.to_datetime(closed_trades["Sell Date"])
    fy_start = np.where(sell_dates.dt.month >= 4, sell_dates.dt.year, sell_dates.dt.year - 1)
    closed_trades["Financial Year"] = [f"FY{str(y)[-2:]}-{str(y + 1)[-2:]}" for y in fy_start]
    closed_trades["Tax Holding Class"] = np.where(closed_trades["Holding Days"] > 365, "LTCG", "STCG")
    post_change = sell_dates >= pd.Timestamp("2024-07-23")
    closed_trades["Indicative Tax Rate %"] = np.where(closed_trades["Tax Holding Class"].eq("STCG"), np.where(post_change, 20.0, 15.0), np.where(post_change, 12.5, 10.0))
    closed_trades["Indicative Gross Tax"] = closed_trades["Realized P&L"].clip(lower=0) * closed_trades["Indicative Tax Rate %"] / 100
    closed_trades["Exit Month"] = pd.to_datetime(closed_trades["Sell Date"]).dt.to_period("M").astype(str)
    monthly_profit = closed_trades.groupby("Exit Month", as_index=False).agg(
        Realized_PnL=("Realized P&L", "sum"), Closed_Lots=("Symbol", "size"), Wins=("Realized P&L", lambda s: int((s > 0).sum())), Average_Return=("Return %", "mean")
    ).rename(columns={"Realized_PnL": "Realized P&L", "Closed_Lots": "Closed Lots", "Average_Return": "Average Return %"})
    monthly_profit["Win Rate %"] = monthly_profit["Wins"] / monthly_profit["Closed Lots"] * 100
    closed_trades["Exit Year"] = pd.to_datetime(closed_trades["Sell Date"]).dt.year
    yearly_profit = closed_trades.groupby("Exit Year", as_index=False).agg(
        Realized_PnL=("Realized P&L", "sum"), Closed_Lots=("Symbol", "size"), Wins=("Realized P&L", lambda s: int((s > 0).sum())), Average_Return=("Return %", "mean")
    ).rename(columns={"Realized_PnL": "Realized P&L", "Closed_Lots": "Closed Lots", "Average_Return": "Average Return %"})
    yearly_profit["Win Rate %"] = yearly_profit["Wins"] / yearly_profit["Closed Lots"] * 100

tax_report = pd.DataFrame()
if not closed_trades.empty:
    tax_report = closed_trades.groupby(["Financial Year", "Tax Holding Class"], as_index=False).agg(
        Realized_Gain_Loss=("Realized P&L", "sum"), Sale_Value=("Sale Amount", "sum"), Cost_Value=("Invested Amount", "sum"), Indicative_Gross_Tax=("Indicative Gross Tax", "sum"), Closed_Lots=("Symbol", "size")
    ).rename(columns={"Realized_Gain_Loss": "Realized Gain/Loss", "Sale_Value": "Sale Value", "Cost_Value": "Cost Value", "Indicative_Gross_Tax": "Indicative Gross Tax", "Closed_Lots": "Closed Lots"})

funds_monthly = pd.DataFrame()
funds_yearly = pd.DataFrame()
if not ledger_df.empty:
    flow_rows = ledger_df.copy()
    flow_rows["Month"] = pd.to_datetime(flow_rows["date"]).dt.to_period("M").astype(str)
    flow_rows["Year"] = pd.to_datetime(flow_rows["date"]).dt.year
    flow_rows["Funds Added"] = np.where(flow_rows["category"].eq("Deposit"), flow_rows["credit"].abs(), 0.0)
    flow_rows["Funds Withdrawn"] = np.where(flow_rows["category"].eq("Withdrawal"), flow_rows["debit"].abs(), 0.0)
    flow_rows["Charges/Taxes"] = np.where(flow_rows["category"].eq("Charges/Taxes"), flow_rows["debit"].abs(), 0.0)
    flow_rows["Dividends"] = np.where(flow_rows["category"].eq("Dividend"), flow_rows["credit"].abs(), 0.0)
    funds_monthly = flow_rows.groupby("Month", as_index=False)[["Funds Added", "Funds Withdrawn", "Charges/Taxes", "Dividends"]].sum()
    funds_monthly["Net Funds Added"] = funds_monthly["Funds Added"] - funds_monthly["Funds Withdrawn"]
    funds_yearly = flow_rows.groupby("Year", as_index=False)[["Funds Added", "Funds Withdrawn", "Charges/Taxes", "Dividends"]].sum()
    funds_yearly["Net Funds Added"] = funds_yearly["Funds Added"] - funds_yearly["Funds Withdrawn"]

history = monthly_portfolio_history(tx, actions)
yearly_report = history.groupby("Year", as_index=False).agg(
    Average_Holdings=("Number of Holdings", "mean"), Average_Invested_Amount=("Invested Amount", "mean"), Maximum_Holdings=("Number of Holdings", "max"), Year_End_Invested_Amount=("Invested Amount", "last")
).rename(columns={"Average_Holdings": "Average Holdings", "Average_Invested_Amount": "Average Invested Amount", "Maximum_Holdings": "Maximum Holdings", "Year_End_Invested_Amount": "Year-end Invested Amount"})

uploaded_value = holdings_df["Uploaded Market Value"].sum() if not holdings_df.empty else np.nan
quality_rows = [
    {"Check": "Tradebook rows parsed", "Actual": len(tx), "Expected": "> 0", "Difference": 0, "Status": "OK" if len(tx) else "FAIL", "Notes": f"Coverage: {tx['date'].min().date()} to {tx['date'].max().date()}"},
    {"Check": "Current holdings loaded", "Actual": len(holdings_df), "Expected": "> 0", "Difference": 0, "Status": "OK" if len(holdings_df) else "REVIEW", "Notes": "Present valuation is authoritative only when holdings are uploaded."},
]
if not holdings_df.empty:
    valuation_difference = market_value - uploaded_value
    quality_rows.append({"Check": "Valuation ties to holdings statement", "Actual": market_value, "Expected": uploaded_value, "Difference": valuation_difference, "Status": "OK" if abs(valuation_difference) < 1 else "FAIL", "Notes": "Yahoo is verification only; manually edited prices can create a difference."})
    mismatch_count = int((reconciliation["Status"] != "Matched").sum()) if not reconciliation.empty else 0
    quality_rows.append({"Check": "Tradebook quantity reconciliation", "Actual": mismatch_count, "Expected": 0, "Difference": mismatch_count, "Status": "OK" if mismatch_count == 0 else "REVIEW", "Notes": "Includes mutual funds absent from the equity tradebook, symbol changes, corporate actions, transfers, and missing history."})
missing_costs = int(edited["Average Cost"].isna().sum())
missing_prices = int(edited["Current Price"].isna().sum())
quality_rows.extend([
    {"Check": "Missing average costs", "Actual": missing_costs, "Expected": 0, "Difference": missing_costs, "Status": "OK" if missing_costs == 0 else "FAIL", "Notes": "Required for cost and return calculations."},
    {"Check": "Missing valuation prices", "Actual": missing_prices, "Expected": 0, "Difference": missing_prices, "Status": "OK" if missing_prices == 0 else "FAIL", "Notes": "Upload value, Yahoo price, or manual price required."},
])
if not ledger_df.empty:
    other_rows = int(ledger_df["category"].eq("Other/Internal").sum())
    quality_rows.append({"Check": "Ledger classification reviewed", "Actual": other_rows, "Expected": "Review", "Difference": 0, "Status": "REVIEW" if other_rows else "OK", "Notes": f"Coverage: {ledger_df['date'].min().date()} to {ledger_df['date'].max().date()}; internal rows do not enter account XIRR."})
quality_report = pd.DataFrame(quality_rows)

tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8, tab9, tab10 = st.tabs(["Holdings", "Deep Analytics", "Heatmaps", "Reconciliation", "Corporate Actions", "Allocation", "Benchmarks", "Risk", "Tradebook", "Funds Ledger"])
with tab1:
    display_cols = [c for c in ["Asset Class", "Sector", "Symbol", "ISIN", "Quantity", "Average Cost", "Current Price", "Yahoo Price", "Yahoo Difference %", "Cost Value", "Market Value", "Unrealized P&L", "Realized P&L", "Return %", "Price Source"] if c in edited.columns]
    st.dataframe(edited[display_cols].style.format({c: "₹{:,.2f}" for c in ["Average Cost", "Current Price", "Cost Value", "Market Value", "Unrealized P&L", "Realized P&L"]}).format({"Quantity": "{:,.4f}", "Return %": "{:.2f}%"}), use_container_width=True)
    st.download_button("Download holdings CSV", edited[display_cols].to_csv(index=False).encode(), "portfolio_holdings.csv", "text/csv")
with tab2:
    st.subheader("Performance leaders and laggards")
    ranked = stock_report.dropna(subset=["Total Return on Purchases %"])
    a1, a2, a3, a4, a5 = st.columns(5)
    if not ranked.empty:
        best_stock = ranked.loc[ranked["Total Return on Purchases %"].idxmax()]
        worst_stock = ranked.loc[ranked["Total Return on Purchases %"].idxmin()]
        a1.metric("Highest-return stock", str(best_stock["Symbol"]), f"{best_stock['Total Return on Purchases %']:.2f}%")
        a2.metric("Lowest-return stock", str(worst_stock["Symbol"]), f"{worst_stock['Total Return on Purchases %']:.2f}%")
    most_traded = stock_report.loc[stock_report["Trades"].idxmax()]
    a3.metric("Most frequently traded", str(most_traded["Symbol"]), f"{int(most_traded['Trades'])} transactions")
    if not closed_trades.empty:
        rankable_trades = closed_trades.dropna(subset=["Return %"])
        if not rankable_trades.empty:
            best_trade = rankable_trades.loc[rankable_trades["Return %"].idxmax()]
            worst_trade = rankable_trades.loc[rankable_trades["Return %"].idxmin()]
            a4.metric("Best closed FIFO lot", str(best_trade["Symbol"]), f"{best_trade['Return %']:.2f}%")
            a5.metric("Worst closed FIFO lot", str(worst_trade["Symbol"]), f"{worst_trade['Return %']:.2f}%")

    st.caption("Stock return = realized P&L + current unrealized P&L ÷ cumulative purchase value. Closed-trade rankings use matched FIFO lots and exclude dividends.")
    st.dataframe(stock_report.sort_values("Total Return on Purchases %", ascending=False), use_container_width=True)
    st.download_button("Download stock analytics", stock_report.to_csv(index=False).encode(), "stock_analytics.csv", "text/csv")

    st.subheader("Holding duration")
    valid_holding = holding_report.dropna(subset=["Weighted Holding Days"])
    h1, h2 = st.columns(2)
    if not valid_holding.empty:
        longest = valid_holding.loc[valid_holding["Weighted Holding Days"].idxmax()]
        shortest = valid_holding.loc[valid_holding["Weighted Holding Days"].idxmin()]
        h1.metric("Longest-held current stock", str(longest["Symbol"]), f"{longest['Weighted Holding Days']:.0f} weighted days")
        h2.metric("Shortest-held current stock", str(shortest["Symbol"]), f"{shortest['Weighted Holding Days']:.0f} weighted days")
    st.dataframe(holding_report.sort_values("Weighted Holding Days", ascending=False), use_container_width=True)

    st.subheader("Closed trades")
    if closed_trades.empty:
        st.info("No sell transaction could be matched with an earlier buy lot.")
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("Closed FIFO lots", f"{len(closed_trades):,}")
        c2.metric("Win rate", f"{(closed_trades['Realized P&L'] > 0).mean() * 100:.2f}%")
        c3.metric("Average holding period", f"{closed_trades['Holding Days'].mean():.0f} days")
        st.dataframe(closed_trades.sort_values("Return %", ascending=False), use_container_width=True)
        st.download_button("Download closed-trade analytics", closed_trades.to_csv(index=False).encode(), "closed_trade_analytics.csv", "text/csv")

    st.subheader("Year-by-year portfolio activity")
    st.caption("Annual averages are calculated from month-end reconstructed FIFO positions; invested amount means remaining cost basis, not market value.")
    st.dataframe(yearly_report, use_container_width=True)
    st.plotly_chart(px.line(yearly_report, x="Year", y=["Average Holdings", "Maximum Holdings"], markers=True, title="Average and maximum holdings by year"), use_container_width=True)
    st.plotly_chart(px.bar(yearly_report, x="Year", y="Average Invested Amount", title="Average month-end invested cost by year"), use_container_width=True)

    st.subheader("Funds added and withdrawn")
    st.caption("These reports use the editable Deposit/Withdrawal classifications confirmed above. Internal trade settlements are excluded.")
    if funds_monthly.empty:
        st.info("Upload and classify the funds ledger to generate monthly and yearly fund-flow reports.")
    else:
        st.markdown("**Monthly fund flows**")
        st.plotly_chart(px.bar(funds_monthly, x="Month", y=["Funds Added", "Funds Withdrawn"], barmode="group", title="Funds added and withdrawn by month"), use_container_width=True)
        st.dataframe(funds_monthly, use_container_width=True)
        st.download_button("Download monthly fund flows", funds_monthly.to_csv(index=False).encode(), "monthly_fund_flows.csv", "text/csv")
        st.markdown("**Yearly fund flows**")
        st.plotly_chart(px.bar(funds_yearly, x="Year", y=["Funds Added", "Funds Withdrawn", "Net Funds Added"], barmode="group", title="Annual fund flows"), use_container_width=True)
        st.dataframe(funds_yearly, use_container_width=True)
        st.download_button("Download yearly fund flows", funds_yearly.to_csv(index=False).encode(), "yearly_fund_flows.csv", "text/csv")

    st.subheader("XIRR cash-flow audit")
    x1, x2 = st.columns(2)
    with x1:
        st.markdown("**Tradebook XIRR inputs**")
        st.dataframe(trade_xirr_audit, use_container_width=True)
        st.download_button("Download tradebook XIRR inputs", trade_xirr_audit.to_csv(index=False).encode(), "tradebook_xirr_inputs.csv", "text/csv")
    with x2:
        st.markdown("**Account XIRR inputs**")
        if account_xirr_audit.empty:
            st.info("Confirm at least one Deposit or Withdrawal in the funds ledger.")
        else:
            st.dataframe(account_xirr_audit, use_container_width=True)
            st.download_button("Download account XIRR inputs", account_xirr_audit.to_csv(index=False).encode(), "account_xirr_inputs.csv", "text/csv")
    st.caption("Negative amounts are capital invested; positive amounts are capital returned. Audit these rows whenever XIRR appears unexpected.")

    st.subheader("Monthly realized profitability")
    st.caption("A month is ranked by realized P&L from FIFO lots sold during that month; current unrealized gains and dividends are excluded.")
    if monthly_profit.empty:
        st.info("Monthly profitability requires at least one matched sell transaction.")
    else:
        p1, p2 = st.columns(2)
        best_month = monthly_profit.loc[monthly_profit["Realized P&L"].idxmax()]
        worst_month = monthly_profit.loc[monthly_profit["Realized P&L"].idxmin()]
        p1.metric("Most profitable exit month", str(best_month["Exit Month"]), money(best_month["Realized P&L"]))
        p2.metric("Least profitable exit month", str(worst_month["Exit Month"]), money(worst_month["Realized P&L"]))
        colors = np.where(monthly_profit["Realized P&L"] >= 0, "Profit", "Loss")
        chart_data = monthly_profit.assign(Result=colors)
        st.plotly_chart(px.bar(chart_data, x="Exit Month", y="Realized P&L", color="Result", color_discrete_map={"Profit": "#16a34a", "Loss": "#dc2626"}, title="Realized P&L by exit month"), use_container_width=True)
        st.dataframe(monthly_profit, use_container_width=True)
        st.download_button("Download monthly profitability", monthly_profit.to_csv(index=False).encode(), "monthly_profitability.csv", "text/csv")

    st.subheader("Yearly realized profitability")
    if yearly_profit.empty:
        st.info("Yearly realized profitability requires at least one matched sell transaction.")
    else:
        st.plotly_chart(px.bar(yearly_profit, x="Exit Year", y="Realized P&L", color="Win Rate %", color_continuous_scale="RdYlGn", title="Realized FIFO P&L by exit year"), use_container_width=True)
        st.dataframe(yearly_profit, use_container_width=True)
        st.download_button("Download yearly profitability", yearly_profit.to_csv(index=False).encode(), "yearly_profitability.csv", "text/csv")

    st.subheader("Indian financial-year capital-gain classification")
    if tax_report.empty:
        st.info("Tax classification requires matched closed FIFO lots.")
    else:
        st.dataframe(tax_report, use_container_width=True)
        st.download_button("Download indicative tax classification", tax_report.to_csv(index=False).encode(), "indicative_tax_report.csv", "text/csv")
        st.caption("Indicative gross tax applies listed-equity STCG/LTCG headline rates by sale date before exemptions, loss set-off, grandfathering, surcharge, and cess. Confirm the final computation with the broker tax P&L and a tax professional.")

    st.subheader("Comprehensive downloadable report")
    if st.checkbox("Prepare Excel and PDF audit reports"):
        summary = pd.DataFrame([
            {"Metric": "Securities value", "Value": market_value}, {"Metric": "Closing cash", "Value": closing_cash},
            {"Metric": "Total account value", "Value": market_value + closing_cash}, {"Metric": "Invested cost", "Value": cost_value},
            {"Metric": "Tradebook XIRR", "Value": portfolio_rate}, {"Metric": "Account XIRR", "Value": account_rate},
            {"Metric": "Realized P&L", "Value": realized_total}, {"Metric": "Unrealized P&L", "Value": market_value - cost_value},
        ])
        report_tables = {
            "Summary": summary, "Quality Checks": quality_report, "Holdings": edited, "Reconciliation": reconciliation,
            "Stock Analytics": stock_report, "Closed FIFO Lots": closed_trades, "Monthly Profit": monthly_profit,
            "Yearly Profit": yearly_profit, "Monthly Fund Flows": funds_monthly, "Yearly Fund Flows": funds_yearly,
            "Tax Classification": tax_report, "Corporate Actions": actions, "Tradebook XIRR Audit": trade_xirr_audit,
            "Account XIRR Audit": account_xirr_audit,
        }
        excel_bytes = excel_report_bytes({k: v for k, v in report_tables.items() if isinstance(v, pd.DataFrame) and not v.empty})
        summary_rows = [["Metric", "Value"]] + [[row["Metric"], money(row["Value"]) if "XIRR" not in row["Metric"] else (f"{row['Value'] * 100:.2f}%" if np.isfinite(row["Value"]) else "N/A")] for _, row in summary.iterrows()]
        pdf_bytes = pdf_report_bytes(summary_rows, quality_report, funds_yearly, yearly_profit)
        d1, d2 = st.columns(2)
        d1.download_button("Download comprehensive Excel report", excel_bytes, "portfolio_comprehensive_report.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        d2.download_button("Download portfolio PDF report", pdf_bytes, "portfolio_audit_report.pdf", "application/pdf")
with tab3:
    st.subheader("Portfolio heatmaps")
    month_labels = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

    if closed_trades.empty:
        st.info("Realized-profit heatmaps require at least one sell matched to an earlier FIFO buy lot.")
    else:
        heat = closed_trades.copy()
        heat["Year"] = pd.to_datetime(heat["Sell Date"]).dt.year
        heat["Month Number"] = pd.to_datetime(heat["Sell Date"]).dt.month
        profit_grid = heat.pivot_table(index="Year", columns="Month Number", values="Realized P&L", aggfunc="sum", fill_value=0).reindex(columns=range(1, 13), fill_value=0)
        fig = go.Figure(go.Heatmap(
            z=profit_grid.values, x=month_labels, y=profit_grid.index.astype(str),
            colorscale="RdYlGn", zmid=0, colorbar_title="Realized P&L",
            text=np.round(profit_grid.values, 2), texttemplate="%{text:,.0f}",
            hovertemplate="Year %{y}<br>%{x}<br>Realized P&L ₹%{z:,.2f}<extra></extra>",
        ))
        fig.update_layout(title="Monthly realized FIFO P&L", xaxis_title="Exit month", yaxis_title="Year", height=max(350, 45 * len(profit_grid)))
        st.plotly_chart(fig, use_container_width=True)

        stock_year = heat.pivot_table(index="Symbol", columns="Year", values="Realized P&L", aggfunc="sum", fill_value=0)
        fig = go.Figure(go.Heatmap(
            z=stock_year.values, x=stock_year.columns.astype(str), y=stock_year.index,
            colorscale="RdYlGn", zmid=0, colorbar_title="Realized P&L",
            hovertemplate="%{y}<br>Year %{x}<br>Realized P&L ₹%{z:,.2f}<extra></extra>",
        ))
        fig.update_layout(title="Stock-by-year realized FIFO P&L", xaxis_title="Year", yaxis_title="Stock", height=max(450, 26 * len(stock_year)))
        st.plotly_chart(fig, use_container_width=True)

    activity = tx.copy()
    activity["Year"] = activity["date"].dt.year
    activity["Month Number"] = activity["date"].dt.month
    activity_grid = activity.pivot_table(index="Year", columns="Month Number", values="symbol", aggfunc="size", fill_value=0).reindex(columns=range(1, 13), fill_value=0)
    fig = go.Figure(go.Heatmap(
        z=activity_grid.values, x=month_labels, y=activity_grid.index.astype(str),
        colorscale="Blues", colorbar_title="Transactions",
        text=activity_grid.values, texttemplate="%{text:.0f}",
        hovertemplate="Year %{y}<br>%{x}<br>%{z:.0f} transactions<extra></extra>",
    ))
    fig.update_layout(title="Monthly trading activity", xaxis_title="Trade month", yaxis_title="Year", height=max(350, 45 * len(activity_grid)))
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Profit heatmaps use realized FIFO P&L by sell date. Trading activity counts tradebook rows. Dividends and unrealized price movements are excluded.")
with tab4:
    st.subheader("Data-quality and reconciliation checks")
    st.dataframe(quality_report, use_container_width=True)
    failed = quality_report[quality_report["Status"].eq("FAIL")]
    if not failed.empty:
        st.error(f"{len(failed)} calculation check(s) failed. Resolve them before relying on final returns.")
    elif quality_report["Status"].eq("REVIEW").any():
        st.warning("Core valuation checks pass, but review items remain for transaction-level/FIFO accuracy.")
    else:
        st.success("All available checks pass.")
    if not isin_symbol_changes.empty:
        st.markdown("**Ticker changes automatically resolved through ISIN**")
        st.dataframe(isin_symbol_changes, use_container_width=True)
    if reconciliation.empty:
        st.info("Upload Current Holdings to compare actual quantities with quantities reconstructed from the tradebook.")
    else:
        mismatches = int((reconciliation["Status"] != "Matched").sum())
        st.metric("Quantity mismatches requiring review", mismatches)
        st.dataframe(reconciliation, use_container_width=True)
        st.caption("Common causes include an incomplete tradebook period, transferred securities, bonuses, splits, mergers, or symbol changes. Current Holdings remains authoritative for today's valuation.")
with tab5:
    if actions.empty:
        st.info("No corporate actions were applied. Add verified actions in the Corporate Actions editor above when applicable.")
    else:
        st.dataframe(actions, use_container_width=True)
        st.download_button("Download applied corporate actions", actions.to_csv(index=False).encode(), "applied_corporate_actions.csv", "text/csv")
    st.markdown("**Treatment:** splits and bonuses preserve total cost; reverse splits change units at the specified ratio; mergers/symbol changes transfer lots; demergers allocate original cost between parent and child using the official percentage.")
with tab6:
    hierarchy = [c for c in ["Asset Class", "Sector", "Symbol"] if c in edited.columns]
    fig = px.treemap(edited, path=hierarchy or ["Symbol"], values="Market Value", color="Return %", color_continuous_scale="RdYlGn", title="Portfolio allocation and returns")
    st.plotly_chart(fig, use_container_width=True)
    if "Sector" in edited.columns:
        sector_summary = edited.groupby(["Asset Class", "Sector"], as_index=False).agg(Market_Value=("Market Value", "sum"), Cost_Value=("Cost Value", "sum"), Unrealized_PnL=("Unrealized P&L", "sum"), Securities=("Symbol", "size"))
        sector_summary["Weight %"] = sector_summary["Market_Value"] / market_value * 100
        sector_summary["Return %"] = np.where(sector_summary["Cost_Value"] != 0, sector_summary["Unrealized_PnL"] / sector_summary["Cost_Value"] * 100, np.nan)
        sector_summary = sector_summary.rename(columns={"Market_Value": "Market Value", "Cost_Value": "Cost Value", "Unrealized_PnL": "Unrealized P&L"})
        st.dataframe(sector_summary.sort_values("Market Value", ascending=False), use_container_width=True)
        st.plotly_chart(px.bar(sector_summary.sort_values("Market Value", ascending=False), x="Sector", y="Weight %", color="Asset Class", title="Sector and asset-class concentration"), use_container_width=True)
        st.download_button("Download sector allocation", sector_summary.to_csv(index=False).encode(), "sector_allocation.csv", "text/csv")
with tab7:
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
        if not external.empty:
            benchmark_units = 0.0
            benchmark_flows, benchmark_dates = [], []
            series_dates = pd.to_datetime(series.index).tz_localize(None) if getattr(series.index, "tz", None) is not None else pd.to_datetime(series.index)
            clean_series = pd.Series(series.values, index=series_dates).sort_index()
            for flow in external.sort_values("date").itertuples():
                available = clean_series[clean_series.index.normalize() >= pd.Timestamp(flow.date).normalize()]
                if available.empty:
                    continue
                cashflow = float(flow.external_cashflow)
                benchmark_units += -cashflow / float(available.iloc[0])
                benchmark_flows.append(cashflow)
                benchmark_dates.append(pd.Timestamp(flow.date).date())
            benchmark_terminal = benchmark_units * float(clean_series.iloc[-1])
            benchmark_rate = xirr(benchmark_flows + [benchmark_terminal], benchmark_dates + [date.today()])
            b1, b2, b3 = st.columns(3)
            b1.metric("Cash-flow-matched benchmark XIRR", f"{benchmark_rate * 100:.2f}%" if np.isfinite(benchmark_rate) else "N/A")
            b2.metric("Benchmark terminal value", money(benchmark_terminal))
            b3.metric("Account wealth vs benchmark", money((market_value + closing_cash) - benchmark_terminal))
            st.caption("Each confirmed deposit buys benchmark units at the next available close; each withdrawal sells units. This is directly cash-flow matched to the account XIRR.")
        else:
            st.caption("Benchmark CAGR is shown because confirmed external ledger cash flows are unavailable for a cash-flow-matched comparison.")
with tab8:
    st.subheader("Snapshot risk analytics")
    st.caption("Uses current equity weights held constant over the selected historical window. It is a risk snapshot, not a reconstruction of past portfolio weights.")
    risk_period = st.selectbox("Risk lookback", ["6mo", "1y", "2y", "5y"], index=1)
    if st.button("Load risk analysis"):
        bench_ticker = {"NIFTY 50 (^NSEI)": "^NSEI", "Gold (GC=F)": "GC=F", "NIFTY 500 (^CRSLDX)": "^CRSLDX"}[benchmark]
        equity_rows = edited[~edited.get("Asset Class", pd.Series("Equity", index=edited.index)).astype(str).str.lower().eq("mutual fund")].copy()
        equity_rows = equity_rows[equity_rows["Yahoo Ticker"].astype(str) != ""]
        with st.spinner("Loading historical prices..."):
            risk_prices = risk_price_history(equity_rows["Yahoo Ticker"].tolist(), bench_ticker, risk_period)
        available = [t for t in equity_rows["Yahoo Ticker"] if t in risk_prices.columns]
        if bench_ticker not in risk_prices.columns or not available:
            st.warning("Insufficient historical price coverage for risk analysis.")
        else:
            returns = risk_prices[available + [bench_ticker]].pct_change().dropna(how="any")
            weight_map = equity_rows.set_index("Yahoo Ticker")["Market Value"].to_dict()
            weights = pd.Series({t: weight_map[t] for t in available}, dtype=float)
            weights /= weights.sum()
            portfolio_daily = returns[available].mul(weights, axis=1).sum(axis=1)
            benchmark_daily = returns[bench_ticker]
            annual_return = (1 + portfolio_daily).prod() ** (252 / max(len(portfolio_daily), 1)) - 1
            annual_vol = portfolio_daily.std() * np.sqrt(252)
            sharpe = (annual_return - risk_free_rate) / annual_vol if annual_vol else np.nan
            downside = portfolio_daily[portfolio_daily < 0].std() * np.sqrt(252)
            sortino = (annual_return - risk_free_rate) / downside if downside else np.nan
            beta = portfolio_daily.cov(benchmark_daily) / benchmark_daily.var() if benchmark_daily.var() else np.nan
            cumulative = (1 + portfolio_daily).cumprod()
            max_drawdown = (cumulative / cumulative.cummax() - 1).min()
            var95 = portfolio_daily.quantile(0.05)
            r1, r2, r3, r4, r5, r6 = st.columns(6)
            r1.metric("Annualized return", f"{annual_return * 100:.2f}%")
            r2.metric("Annualized volatility", f"{annual_vol * 100:.2f}%")
            r3.metric("Sharpe", f"{sharpe:.2f}" if np.isfinite(sharpe) else "N/A")
            r4.metric("Sortino", f"{sortino:.2f}" if np.isfinite(sortino) else "N/A")
            r5.metric("Beta", f"{beta:.2f}" if np.isfinite(beta) else "N/A")
            r6.metric("Maximum drawdown", f"{max_drawdown * 100:.2f}%")
            st.metric("Historical one-day VaR (95%)", f"{var95 * 100:.2f}%")
            risk_curve = pd.DataFrame({"Portfolio": cumulative, benchmark: (1 + benchmark_daily).cumprod()}) * 100
            st.plotly_chart(px.line(risk_curve, title="Growth of 100 — current-weight risk snapshot"), use_container_width=True)
            corr = returns[available].corr()
            fig = go.Figure(go.Heatmap(z=corr.values, x=corr.columns, y=corr.index, zmin=-1, zmax=1, zmid=0, colorscale="RdBu", colorbar_title="Correlation"))
            fig.update_layout(title="Holding return correlations", height=max(500, 22 * len(corr)))
            st.plotly_chart(fig, use_container_width=True)
            coverage = pd.DataFrame({"Yahoo Ticker": equity_rows["Yahoo Ticker"], "Included": equity_rows["Yahoo Ticker"].isin(available)})
            st.dataframe(coverage, use_container_width=True)
with tab9:
    st.dataframe(tx, use_container_width=True)
    st.download_button("Download normalized transactions", tx.to_csv(index=False).encode(), "normalized_transactions.csv", "text/csv")
with tab10:
    if ledger_df.empty:
        st.info("Upload and map the separate funds ledger statement to see deposits, withdrawals, charges, dividends, and account cash flows.")
    else:
        st.dataframe(ledger_df, use_container_width=True)
        category_summary = ledger_df.groupby("category", as_index=False).agg(Entries=("date", "size"), Debit=("debit", "sum"), Credit=("credit", "sum"))
        st.plotly_chart(px.bar(category_summary, x="category", y=["Debit", "Credit"], barmode="group", title="Funds-ledger classification"), use_container_width=True)
        st.download_button("Download normalized funds ledger", ledger_df.to_csv(index=False).encode(), "normalized_funds_ledger.csv", "text/csv")

st.caption("Market information may be delayed or unavailable. Verify important values independently; this dashboard is not investment advice.")
