# Collateral Management & SBL Simulator

A Streamlit dashboard simulating core fixed income operations across three modules: repo trade lifecycle, securities borrowing & lending settlement tracking, and a business rules engine for collateral management systems.

---

## Problem

Collateral management desks at broker-dealers and custodians (repo desks, SBL teams, post-trade operations) need to:
- Monitor collateral coverage in real time and trigger margin calls when prices move
- Track settlement status across dozens of daily SBL transactions and resolve fails quickly
- Enforce precise business rules (haircuts, coverage thresholds, 102% SBL collateral, T+2 settlement) without error

These workflows are operationally intensive, high-stakes, and difficult to visualize without proprietary systems.

## Solution

This simulator models those workflows end-to-end in an interactive dashboard, covering three modules built on the same data layer.

---

## Architecture

```
app.py                      # Streamlit dashboard — 3 modules
├── data_models.py          # Core data classes: Collateral, RepoTrade, SBLTransaction, Position
├── repo_engine.py          # Day-by-day repo lifecycle simulation
├── margin_engine.py        # Margin call detection, resolution, close-out P&L
├── sbl_engine.py           # SBL portfolio generation, settlement simulation, exposure aggregation
├── schema.sql              # Relational DB schema (5 tables) + 8 analytical queries
└── tests/
    ├── test_margin_engine.py   # 26 tests: collateral, margin calls, lifecycle scenarios
    └── test_sbl_engine.py      # 30 tests: positions, transactions, settlement, exposure
```

---

## Modules

### 📄 Repo Trade Lifecycle
Models a full repurchase agreement from open to close:
- Configurable collateral type (Treasuries, MBS, CMBS, ABS, IG Corp) with market-standard haircuts
- Five price scenarios: stable, gradual decline, sharp drop, recovery, volatile
- Automatic margin call detection when coverage drops below threshold
- Three resolution paths: cash top-up, collateral substitution, default/close-out
- Trade roll at maturity with configurable new rate and term
- Live risk alerts (🔴 critical / 🟠 warning / ✅ OK) based on current coverage ratio
- Lifecycle event log with cash flow tracking

### 🔄 SBL Settlement Tracker
Simulates a collateral management operations desk:
- Portfolio of 12 Canadian securities (equities, government bonds, ETFs, corporate bonds) with configurable availability
- Transaction log with full detail: counterparty, ticker, notional, required collateral (102%), rate, settlement date, T+offset
- Settlement fail monitoring with realistic fail reasons (DTCC holds, delivery failures, corporate action freezes)
- Live alerts for undercollateralized counterparties and high-value settlement fails
- Counterparty exposure aggregation with undercollateralization flags
- Daily fee income tracking

### 📐 Business Rules Engine
Ten business rules tested live against configurable inputs:

| ID | Domain | Rule |
|---|---|---|
| RULE-001 | Repo | Eligible Value = MV × (1 − Haircut) |
| RULE-002 | Repo | Coverage Ratio = Eligible Value / Cash Lent |
| RULE-003 | Repo | Margin Call if shortfall > 2% of Cash Lent |
| RULE-004 | Repo | Cash Lent ≤ Eligible Value |
| RULE-005 | SBL | Required Collateral = 102% of Notional |
| RULE-006 | SBL | SBL Coverage ≥ 102% |
| RULE-007 | Settlement | Standard Settlement = T+2 |
| RULE-008 | Settlement | Daily Mark-to-Market required |
| RULE-009 | Interest | Repo Accrual = Cash × Rate / 360 |
| RULE-010 | Interest | SBL Fee = Notional × Rate / 360 |

Each rule displays: Condition → Expected → Observed → PASS/FAIL.

---

## Getting Started

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Running Tests

```bash
pytest tests/ -v
```

56 tests · 100% pass rate

---

## Database Schema

`schema.sql` defines a normalized relational model: `repo_trades`, `lifecycle_events`, `sbl_transactions`, `portfolio_positions`, `collateral_exposure_snapshots`.

Eight analytical queries cover daily desk workflows: trades maturing today, active margin calls, settlement fails, counterparty coverage report, daily fee income by asset class.

---

## Market-Standard Parameters

| Asset Class | Repo Haircut | SBL Rate Range |
|---|---|---|
| US Treasury | 2.0% | 0.10% – 1.50% |
| MBS | 5.0% | 0.50% – 8.50% |
| CMBS | 8.0% | 0.50% – 8.50% |
| ABS | 7.0% | 0.50% – 8.50% |
| IG Corporate Bond | 6.0% | 0.80% – 4.00% |
| Equity | — | 0.30% – 8.50% |

---

## Future Improvements

- Connect to live market data feed (FRED API) for real-time collateral price updates
- Add multi-trade portfolio view with aggregate desk exposure across all open repos
- Implement substitution ladder: auto-suggest optimal collateral substitution on margin call
- Add SWIFT/FIX message simulation for settlement confirmation workflow
- Historical backtesting of margin call frequency by asset class and market regime

---

Built by Steve Rudy Komguep Jouenang — BCom Finance, Telfer School of Management
