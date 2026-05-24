"""
SBL Engine — Securities Borrowing & Lending simulation.
Generates a realistic portfolio of positions and SBL transactions,
simulates settlement, failures, and collateral coverage.
"""

from datetime import date, timedelta
from typing import List, Tuple
import random
from data_models import (
    Position, SBLTransaction, CollateralExposure,
    AssetClass, CollateralType, LoanDirection, SettlementStatus
)

# ── Sample universe ───────────────────────────────────────────────────────────

SAMPLE_POSITIONS = [
    ("RY.TO",  "Royal Bank of Canada",        AssetClass.EQUITY,        50_000, 138.50),
    ("TD.TO",  "TD Bank",                     AssetClass.EQUITY,        45_000, 82.30),
    ("CNR.TO", "Canadian National Railway",   AssetClass.EQUITY,        30_000, 167.20),
    ("SU.TO",  "Suncor Energy",               AssetClass.EQUITY,        60_000, 58.40),
    ("BNS.TO", "Bank of Nova Scotia",         AssetClass.EQUITY,        40_000, 71.80),
    ("GOC5",   "GoC 5Y Bond 3.25% 2029",      AssetClass.GOVERNMENT_BOND, 200,  98_250.0),
    ("GOC10",  "GoC 10Y Bond 3.50% 2034",     AssetClass.GOVERNMENT_BOND, 150, 96_800.0),
    ("CM.TO",  "CIBC",                        AssetClass.EQUITY,        35_000, 89.60),
    ("BCE.TO", "BCE Inc.",                    AssetClass.EQUITY,        55_000, 33.20),
    ("XIC.TO", "iShares Core S&P/TSX ETF",   AssetClass.ETF,           80_000, 37.90),
    ("ENB.TO", "Enbridge Inc.",               AssetClass.EQUITY,        70_000, 62.10),
    ("IBCORP1","NBC IG Corp Bond 4.1% 2028",  AssetClass.CORPORATE_BOND, 100, 97_500.0),
]

COUNTERPARTIES = [
    "Citadel Securities",
    "Jane Street Capital",
    "Millennium Management",
    "Two Sigma Investments",
    "Point72 Asset Management",
    "Virtu Financial",
]

FAIL_REASONS = [
    "Insufficient securities at DTC",
    "Counterparty failed to deliver collateral",
    "DTCC hold — corporate action pending",
    "Late confirmation from prime broker",
    "Collateral substitution in progress",
]


def build_sample_portfolio(seed: int = 42) -> List[Position]:
    random.seed(seed)
    positions = []
    for ticker, name, asset_class, qty, price in SAMPLE_POSITIONS:
        atl = round(random.uniform(0.55, 0.95), 2)
        positions.append(Position(
            ticker=ticker,
            name=name,
            asset_class=asset_class,
            quantity=qty,
            market_price=price,
            available_to_lend=atl,
        ))
    return positions


def generate_sbl_transactions(
    positions: List[Position],
    n_transactions: int = 18,
    fail_rate: float = 0.15,
    seed: int = 42,
) -> List[SBLTransaction]:
    """Generate a realistic set of SBL transactions across the portfolio."""
    random.seed(seed)
    transactions = []
    today = date.today()

    for i in range(n_transactions):
        pos = random.choice(positions)
        direction = random.choice([LoanDirection.LEND, LoanDirection.BORROW])
        counterparty = random.choice(COUNTERPARTIES)

        max_qty = pos.lendable_quantity if direction == LoanDirection.LEND else pos.quantity
        qty = max(1, int(max_qty * random.uniform(0.1, 0.6)))

        # Rates vary by asset class
        rate_range = {
            AssetClass.EQUITY: (0.003, 0.085),
            AssetClass.GOVERNMENT_BOND: (0.001, 0.015),
            AssetClass.CORPORATE_BOND: (0.008, 0.04),
            AssetClass.ETF: (0.002, 0.025),
        }
        lo, hi = rate_range[pos.asset_class]
        rate = round(random.uniform(lo, hi), 4)

        col_type = random.choice([
            CollateralType.TREASURY,
            CollateralType.MBS,
            CollateralType.IG_CORP,
        ])

        # Settlement date: T+1 or T+2
        t_offset = random.choice([0, 1, 2])
        trade_date = today - timedelta(days=random.randint(0, 3))
        settlement_date = trade_date + timedelta(days=t_offset + 1)

        # Assign status
        rand = random.random()
        if settlement_date < today:
            if rand < fail_rate:
                status = SettlementStatus.FAILED
                fail_reason = random.choice(FAIL_REASONS)
            elif rand < fail_rate + 0.08:
                status = SettlementStatus.PARTIAL
                fail_reason = "Partial delivery — 60% filled"
            else:
                status = SettlementStatus.SETTLED
                fail_reason = ""
        elif settlement_date == today:
            status = SettlementStatus.PENDING
            fail_reason = ""
        else:
            status = SettlementStatus.PENDING
            fail_reason = ""

        transactions.append(SBLTransaction(
            transaction_id=f"SBL-{2026_0000 + i + 1:08d}",
            direction=direction,
            counterparty=counterparty,
            position=pos,
            quantity=qty,
            rate=rate,
            collateral_type=col_type,
            trade_date=trade_date,
            settlement_date=settlement_date,
            term_days=random.choice([1, 1, 1, 7, 30]),
            status=status,
            fail_reason=fail_reason,
        ))

    return transactions


def compute_counterparty_exposures(
    transactions: List[SBLTransaction],
) -> List[CollateralExposure]:
    """Aggregate collateral exposure by counterparty."""
    from collections import defaultdict
    data = defaultdict(lambda: {
        "lent": 0.0, "collateral": 0.0, "open": 0, "failed": 0
    })

    for t in transactions:
        if t.direction == LoanDirection.LEND and t.status != SettlementStatus.FAILED:
            d = data[t.counterparty]
            d["lent"] += t.notional_value
            d["collateral"] += t.required_collateral * random.uniform(0.97, 1.03)
            d["open"] += 1 if t.status == SettlementStatus.PENDING else 0
            d["failed"] += 1 if t.status == SettlementStatus.FAILED else 0

    exposures = []
    for cp, d in data.items():
        lent = d["lent"]
        coll = d["collateral"]
        ratio = coll / lent if lent > 0 else 0
        exposures.append(CollateralExposure(
            counterparty=cp,
            total_lent_value=lent,
            total_collateral_received=coll,
            coverage_ratio=ratio,
            open_transactions=d["open"],
            failed_settlements=d["failed"],
        ))

    return sorted(exposures, key=lambda x: x.total_lent_value, reverse=True)


def settlement_summary(transactions: List[SBLTransaction]) -> dict:
    total = len(transactions)
    settled = sum(1 for t in transactions if t.status == SettlementStatus.SETTLED)
    failed = sum(1 for t in transactions if t.status == SettlementStatus.FAILED)
    pending = sum(1 for t in transactions if t.status == SettlementStatus.PENDING)
    partial = sum(1 for t in transactions if t.status == SettlementStatus.PARTIAL)

    total_notional = sum(t.notional_value for t in transactions)
    failed_notional = sum(t.notional_value for t in transactions if t.status == SettlementStatus.FAILED)
    daily_fees = sum(t.daily_fee for t in transactions if t.direction == LoanDirection.LEND
                     and t.status == SettlementStatus.SETTLED)

    return {
        "total": total,
        "settled": settled,
        "failed": failed,
        "pending": pending,
        "partial": partial,
        "settlement_rate": settled / total if total else 0,
        "total_notional": total_notional,
        "failed_notional": failed_notional,
        "daily_fees_earned": daily_fees,
    }
