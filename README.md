# Portfolio Command Center

A single-file, ledger-first Streamlit portfolio dashboard with three separate uploads: a tradebook, a funds ledger statement, and current holdings. It works without a Zerodha login or Kite Connect subscription.

## Features

- Imports CSV, XLSX, and XLS trade ledgers
- Provides separate Tradebook, Funds Ledger, and Current Holdings upload fields
- Treats uploaded current holdings as the authoritative present-day quantity snapshot
- Reconciles holdings quantities against positions reconstructed from the tradebook
- Applies verified splits, reverse splits, bonuses, mergers, symbol changes, and demergers during FIFO lot reconstruction
- Optionally retrieves Yahoo split/bonus candidates for manual verification
- Ranks highest- and lowest-return stocks and best/worst closed FIFO lots
- Identifies the most frequently traded security
- Measures longest and shortest weighted holding periods
- Calculates average and maximum holdings for each year from month-end snapshots
- Calculates average and year-end invested cost for each year
- Ranks the most and least profitable exit months using realized FIFO P&L
- Summarizes funds added, withdrawn, charges, dividends, and net additions monthwise and yearwise
- Summarizes realized FIFO profit, closed lots, average return, and win rate monthwise and yearwise
- Reports win rate, average holding duration, and downloadable analytics tables
- Provides downloadable tradebook-XIRR and account-XIRR cash-flow audit tables
- Includes a dedicated Heatmaps tab for monthly realized P&L, monthly trading activity, and stock-by-year realized P&L
- Consolidates Zerodha Equity and Mutual Funds holdings worksheets automatically
- Uses ISIN to resolve ticker-name changes between tradebook and current holdings
- Uses Zerodha voucher types plus editable classifications for complete external cash flows
- Provides cash-flow-matched benchmark XIRR and terminal-wealth comparison
- Provides current-weight risk analytics: volatility, Sharpe, Sortino, beta, drawdown, VaR, and correlation
- Produces downloadable comprehensive Excel and PDF audit reports
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

## Comprehensive analytics definitions

- **Stock return:** total realized P&L plus current unrealized P&L, divided by cumulative purchase value. It excludes dividends, which are shown separately from the funds ledger.
- **Closed trade:** each FIFO lot portion matched when a sell is processed. It has its own purchase price/date, sale price/date, return, P&L, and holding days.
- **Holding duration:** quantity-weighted age of currently open FIFO lots. Securities present only in the current-holdings export may lack a reliable start date when historical trades are absent.
- **Average annual holdings/investment:** averages of reconstructed month-end holding counts and remaining cost basis for each calendar year.
- **Monthly profitability:** realized FIFO P&L grouped by sell month. It excludes unrealized gains and dividends, so the report does not mislabel market movements as booked profit.
- **Monthly/yearly funds added:** only rows confirmed as Deposit or Withdrawal in the editable ledger classification are counted. Trade settlements and other internal movements are excluded.
- **Valuation:** when a current-holdings export supplies current value or LTP, it is authoritative. Yahoo is shown only as an independent verification difference and does not silently overwrite the broker snapshot.

## Zerodha reconciliation conventions

- Every recognizable worksheet in the holdings workbook is consolidated; Equity and Mutual Funds are never silently dropped.
- Current holdings quantities and statement prices/values are authoritative for present valuation.
- The equity tradebook is used for FIFO realized P&L and trade analytics. Mutual-fund holdings without transaction history enter account valuation and account XIRR, but not scheme-level FIFO/XIRR.
- ISIN mapping resolves ticker changes where old and current symbols share an ISIN.
- `Bank Receipts` and `Bank Payments` voucher types seed external deposits and withdrawals. The user can correct every category before XIRR.
- Account XIRR uses confirmed external flows plus current holdings value and the final dated ledger cash balance.

## Tax-report caveat and official references

The tax tab is indicative. It classifies matched listed-equity FIFO lots as short- or long-term and applies headline rates by sale date before exemptions, grandfathering, loss set-off, surcharge, and cess. It is not an income-tax return computation. Verify against the broker tax P&L and professional advice.

- Finance (No. 2) Bill 2024: https://www.indiabudget.gov.in/budget2024-25/doc/Finance_Bill.pdf
- Income Tax e-filing portal: https://www.incometax.gov.in/

For live mutual-fund valuation, Yahoo must recognize the uploaded scheme identifier. When it does not, simply enter the latest NAV in the editable Current Price column.

## Important notes

- Yahoo Finance data can be delayed or unavailable.
- The NIFTY and gold display is a period comparison, not a cash-flow-matched benchmark XIRR.
- Taxes, dividends, corporate actions, fees, short positions, and derivatives require additional treatment and are not automatically inferred.
- This application is an analytics tool, not investment advice.
