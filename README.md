# Portfolio Command Center

A single-file, ledger-first Streamlit portfolio dashboard with three separate uploads: a tradebook, a funds ledger statement, and current holdings. It works without a Zerodha login or Kite Connect subscription.

## Features

- Imports CSV, XLSX, and XLS trade ledgers
- Provides separate Tradebook, Funds Ledger, and Current Holdings upload fields
- Treats uploaded current holdings as the authoritative present-day quantity snapshot
- Reconciles holdings quantities against positions reconstructed from the tradebook
- Applies verified splits, reverse splits, bonuses, mergers, symbol changes, and demergers during FIFO lot reconstruction
- Optionally retrieves Yahoo split/bonus candidates for manual verification
- Classifies ledger deposits, withdrawals, charges/taxes, dividends, and internal entries
- Recognizes common Zerodha and mutual-fund ledger column names
- Detects headings below title/summary rows in broker Excel exports
- Lets you manually map unfamiliar columns
- Reconstructs open long positions with FIFO lots
- Calculates realized and unrealized profit/loss
- Calculates cash-flow-correct portfolio XIRR
- Checks current prices through Yahoo Finance
- Allows manual price editing when Yahoo data is missing
- Shows interactive Plotly holdings, allocation, and benchmark charts
- Compares the ledger period with NIFTY 50, NIFTY 500, or gold
- Exports normalized transactions and calculated holdings

## Run locally

1. Extract the ZIP.
2. Open a terminal in the extracted folder.
3. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

4. Start the app:

   ```bash
   streamlit run app.py
   ```

## Deploy on GitHub and Streamlit Community Cloud

1. Upload `app.py`, `README.md`, and `requirements.txt` to the root of your GitHub repository.
2. In Streamlit Community Cloud, choose the repository and set the main file path to `app.py`.
3. Deploy. No secrets and no Zerodha connection are required.

## File A: Tradebook columns

The app needs:

- Transaction date
- Symbol, trading symbol, scheme name, or fund name
- Quantity or units
- Price/NAV, or an amount from which price can be derived

A transaction-type column containing values such as Buy, Sell, Purchase, Redemption, SIP, Switch In, or Switch Out is recommended. Without one, sell/redemption quantities must be negative.

## File B: Funds ledger columns

The separate funds ledger needs:

- Date or posting date
- Particulars, narration, or description
- Debit and/or credit
- Balance (optional)

The app automatically classifies likely deposits, withdrawals, charges/taxes, dividends, and internal entries. Because broker narrations vary, review these categories before relying on ledger-adjusted XIRR.

Zerodha's **funds ledger statement** normally contains only cash debits and credits, so it cannot reconstruct stock quantities or purchase prices by itself. The tradebook drives holdings and FIFO P&L; the funds ledger separately supplies account cash-flow information.

## File C: Current holdings columns

The current holdings export needs:

- Symbol or instrument
- Quantity
- Average cost (strongly recommended)
- LTP/current price or current value (optional because Yahoo/manual pricing is available)

When supplied, the holdings file becomes authoritative for today's quantities and cost snapshot. A dedicated reconciliation table compares it with the tradebook reconstruction and flags differences caused by incomplete date ranges, transfers, splits, bonuses, mergers, or symbol changes.

## Corporate actions

Use the in-app corporate-action register before valuation:

- **Split / reverse split / bonus:** enter the post-action shares divided by pre-action shares. Total cost is preserved and per-share cost is adjusted.
- **Symbol change / merger:** enter the old and new symbols plus the exchange ratio. Existing FIFO lots and cost move to the new symbol.
- **Demerger:** enter parent and child symbols, entitlement ratio, and the official percentage of original cost allocated to the child. The remainder stays with the parent.

Yahoo split/bonus checking is a candidate finder, not an authoritative corporate-action source. Verify every candidate against an NSE/BSE filing or company announcement. Demerger cost allocation normally requires the company's official shareholder tax notice and must be entered manually. Dividends remain cash-flow entries in the funds ledger and are never treated as quantity adjustments.

For live mutual-fund valuation, Yahoo must recognize the uploaded scheme identifier. When it does not, simply enter the latest NAV in the editable Current Price column.

## Important notes

- Yahoo Finance data can be delayed or unavailable.
- The NIFTY and gold display is a period comparison, not a cash-flow-matched benchmark XIRR.
- Taxes, dividends, corporate actions, fees, short positions, and derivatives require additional treatment and are not automatically inferred.
- This application is an analytics tool, not investment advice.
