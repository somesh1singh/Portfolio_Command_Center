# Portfolio Command Center

A deployable Streamlit application for Indian equity portfolio tracking. It imports Zerodha-style tradebooks and generic ledgers, reconstructs holdings, verifies market prices through Yahoo Finance, calculates money-weighted returns (XIRR), and renders interactive Plotly analytics.

> This app is analytics-only. It does not place orders. No Zerodha connection is required: ledger upload is the primary workflow. Zerodha holdings/order APIs require a paid Kite Connect subscription and are only an optional price cross-check here.

## Features

- CSV/XLSX ledger parsing with automatic column matching
- FIFO realized P&L and current open positions
- Yahoo Finance price verification (`.NS` / `.BO` mapping)
- Per-security and total portfolio XIRR
- Allocation, P&L, value-history and benchmark charts
- Data-quality warnings, duplicate removal and downloadable normalized data
- Optional Zerodha quote verification using `api_key` + `access_token`
- Demo ledger for an immediate first run

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

## Ledger format

The parser recognizes common names automatically. The minimum fields are:

| Canonical field | Examples accepted | Required |
|---|---|---|
| date | trade_date, transaction_date | Yes |
| symbol | tradingsymbol, ticker, scrip | Yes |
| side | trade_type, transaction_type, buy/sell | Yes |
| quantity | qty, units | Yes |
| price | trade_price, average_price, rate | Yes |
| charges | brokerage, fees, taxes | No |
| exchange | NSE, BSE | No |

BUY quantities may be positive and SELL quantities positive or negative. Side labels are normalized. Charges should be positive.

## GitHub + Streamlit Community Cloud

1. Create a GitHub repository and upload all files in this project.
2. Do **not** commit `.streamlit/secrets.toml`; it is excluded by `.gitignore`.
3. In Streamlit Community Cloud, choose `app.py` as the entry point.
4. Add optional credentials in the app's Secrets settings:

```toml
[zerodha]
api_key = "..."
access_token = "..."
```

Access tokens expire daily. Without credentials, Yahoo verification and uploaded ledgers continue to work.

## Notes

- Yahoo prices can be delayed and are not execution-grade. The dashboard displays timestamps and warns on stale data.
- XIRR needs at least one negative and one positive cash flow. Open positions add a terminal positive cash flow at the valuation date.
- Corporate actions (splits, bonuses, mergers) should be reflected in the uploaded ledger or adjusted manually before relying on cost/P&L.
- Mutual funds can be imported if Yahoo supports the symbol, but Indian AMFI NAV integration is not included in this version.

## Tests

```bash
pytest -q
```
