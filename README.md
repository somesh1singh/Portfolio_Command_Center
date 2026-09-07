# Portfolio Command Center

A single-file, ledger-first Streamlit portfolio dashboard. It works without a Zerodha login or Kite Connect subscription.

## Features

- Imports CSV, XLSX, and XLS trade ledgers
- Recognizes common Zerodha and mutual-fund ledger column names
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

## Ledger columns

The app needs:

- Transaction date
- Symbol, trading symbol, scheme name, or fund name
- Quantity or units
- Price/NAV, or an amount from which price can be derived

A transaction-type column containing values such as Buy, Sell, Purchase, Redemption, SIP, Switch In, or Switch Out is recommended. Without one, sell/redemption quantities must be negative.

For live mutual-fund valuation, Yahoo must recognize the uploaded scheme identifier. When it does not, simply enter the latest NAV in the editable Current Price column.

## Important notes

- Yahoo Finance data can be delayed or unavailable.
- The NIFTY and gold display is a period comparison, not a cash-flow-matched benchmark XIRR.
- Taxes, dividends, corporate actions, fees, short positions, and derivatives require additional treatment and are not automatically inferred.
- This application is an analytics tool, not investment advice.
