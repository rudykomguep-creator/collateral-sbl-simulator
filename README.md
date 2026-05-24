# Collateral Management & SBL Simulator

A Streamlit dashboard simulating core fixed income operations: repo trade lifecycle management and securities borrowing & lending settlement tracking.

## Overview

This project models two interconnected workflows found at major broker-dealers and custodians:

**Repo Trade Lifecycle** — A repurchase agreement simulator covering trade open, daily collateral monitoring, margin call detection and resolution (cash top-up, collateral substitution, or client default), trade rolls at maturity, and close-out P&L calculation.

**SBL Settlement Tracker** — A securities borrowing and lending operations dashboard covering portfolio availability analysis across equity, fixed income, and ETF positions, settlement fail monitoring, counterparty collateral exposure, and daily fee income tracking.

## Features

- Interactive trade configuration via sidebar (collateral type, haircut, repo rate, term, margin threshold)
- Five configurable collateral price scenarios including gradual decline, sharp drop, and volatile paths
- Real-time coverage ratio monitoring with automatic margin call triggers
- Three margin call resolution paths: cash, collateral substitution, default/close-out
- SBL portfolio with 12 Canadian securities across four asset classes
- Counterparty exposure table with undercollateralization flags
- Settlement fail log with realistic fail reasons
- Plotly visualizations: collateral MV vs coverage ratio, cumulative cash flows, settlement donut chart

## Getting Started

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Running Tests

```bash
pytest tests/ -v
```

56 tests covering margin call logic, coverage ratio calculations, settlement summary accuracy, collateral exposure aggregation, and full lifecycle simulation across multiple scenarios.

## Project Structure

```
├── app.py                          # Streamlit dashboard (two-page)
├── data_models.py                  # Core data classes: Collateral, RepoTrade, SBLTransaction
├── repo_engine.py                  # Day-by-day repo lifecycle simulation
├── margin_engine.py                # Margin call detection and resolution
├── sbl_engine.py                   # SBL portfolio generation and settlement tracking
├── schema.sql                      # Relational database schema + 8 analytical queries
├── requirements.txt
└── tests/
    ├── test_margin_engine.py       # 26 tests: collateral, margin calls, lifecycle
    └── test_sbl_engine.py          # 30 tests: positions, transactions, settlement, exposure
```

## Database Schema

`schema.sql` defines a normalized relational model for persisting all operations data, including tables for `repo_trades`, `lifecycle_events`, `sbl_transactions`, `portfolio_positions`, and `collateral_exposure_snapshots`.

Eight analytical queries are included covering daily trader checklists (trades maturing today, active margin calls), operations reporting (settlement fails, counterparty coverage), and P&L tracking (daily fee income by counterparty and asset class).

## Market-Standard Parameters

| Asset Class | Haircut | Lending Rate Range |
|---|---|---|
| US Treasury | 2.0% | 0.10% – 1.50% |
| MBS | 5.0% | 0.50% – 8.50% |
| CMBS | 8.0% | 0.50% – 8.50% |
| ABS | 7.0% | 0.50% – 8.50% |
| IG Corporate Bond | 6.0% | 0.80% – 4.00% |
| Equity | — | 0.30% – 8.50% |

---

Built by Steve Rudy Komguep Jouenang — BCom Finance, Telfer School of Management
