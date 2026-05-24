"""
Data models for the Repo Trade Lifecycle Simulator.
Defines core objects: Collateral, RepoTrade, MarginCall, LifecycleEvent.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Optional
from enum import Enum


class CollateralType(Enum):
    TREASURY = "US Treasury"
    MBS = "MBS (Mortgage-Backed)"
    CMBS = "CMBS (Commercial MBS)"
    ABS = "ABS (Asset-Backed)"
    IG_CORP = "IG Corporate Bond"


class TradeStatus(Enum):
    OPEN = "Open"
    MARGIN_CALL_PENDING = "Margin Call Pending"
    ROLLED = "Rolled"
    CLOSED = "Closed"
    DEFAULTED = "Defaulted"


class EventType(Enum):
    OPEN = "Trade Opened"
    MARGIN_CALL = "Margin Call Issued"
    MARGIN_MET = "Margin Call Met"
    SUBSTITUTION = "Collateral Substitution"
    ROLL = "Trade Rolled"
    CLOSE = "Trade Closed"
    DEFAULT = "Default / Close-Out"


# Standard haircuts per collateral type (industry approximations)
STANDARD_HAIRCUTS = {
    CollateralType.TREASURY: 0.02,      # 2%
    CollateralType.MBS: 0.05,           # 5%
    CollateralType.CMBS: 0.08,          # 8%
    CollateralType.ABS: 0.07,           # 7%
    CollateralType.IG_CORP: 0.06,       # 6%
}


@dataclass
class Collateral:
    collateral_type: CollateralType
    face_value: float          # Par value of the bond
    market_value: float        # Current market price
    cusip: str = "N/A"
    haircut_override: Optional[float] = None

    @property
    def haircut(self) -> float:
        if self.haircut_override is not None:
            return self.haircut_override
        return STANDARD_HAIRCUTS[self.collateral_type]

    @property
    def eligible_value(self) -> float:
        """Value after haircut — what MS will lend against."""
        return self.market_value * (1 - self.haircut)

    def apply_price_change(self, pct_change: float) -> "Collateral":
        """Return new Collateral with updated market value."""
        new_mv = self.market_value * (1 + pct_change)
        return Collateral(
            collateral_type=self.collateral_type,
            face_value=self.face_value,
            market_value=new_mv,
            cusip=self.cusip,
            haircut_override=self.haircut_override,
        )


@dataclass
class LifecycleEvent:
    day: int
    event_type: EventType
    description: str
    cash_flow: float = 0.0        # Positive = MS receives, Negative = MS pays
    collateral_value: float = 0.0
    trade_status: TradeStatus = TradeStatus.OPEN


@dataclass
class MarginCall:
    day: int
    shortfall_amount: float
    coverage_ratio: float
    resolved: bool = False
    resolution: str = ""


@dataclass
class RepoTrade:
    # Trade parameters
    client_name: str
    collateral: Collateral
    cash_lent: float               # Amount MS lends to client
    repo_rate: float               # Annual rate (e.g. 0.053 = 5.30%)
    start_date: date
    term_days: int                 # 1 = overnight, 7 = 1 week, etc.
    margin_threshold: float = 0.02 # Trigger margin call if shortfall > 2%

    # State
    status: TradeStatus = TradeStatus.OPEN
    events: list = field(default_factory=list)

    @property
    def daily_interest(self) -> float:
        return self.cash_lent * self.repo_rate / 360

    @property
    def total_interest(self) -> float:
        return self.daily_interest * self.term_days

    @property
    def repurchase_price(self) -> float:
        """Total amount client must repay at maturity."""
        return self.cash_lent + self.total_interest

    def coverage_ratio(self, current_collateral_mv: float) -> float:
        """Ratio of collateral eligible value to cash lent."""
        eligible = current_collateral_mv * (1 - self.collateral.haircut)
        return eligible / self.cash_lent

    def shortfall(self, current_collateral_mv: float) -> float:
        """
        Positive = shortfall (need more collateral).
        Negative = excess coverage.
        """
        eligible = current_collateral_mv * (1 - self.collateral.haircut)
        return self.cash_lent - eligible


# ── SBL Models ────────────────────────────────────────────────────────────────

class AssetClass(Enum):
    EQUITY = "Equity"
    GOVERNMENT_BOND = "Government Bond"
    CORPORATE_BOND = "Corporate Bond"
    ETF = "ETF"


class SettlementStatus(Enum):
    PENDING = "Pending"
    SETTLED = "Settled"
    FAILED = "Failed"
    PARTIAL = "Partial Fill"


class LoanDirection(Enum):
    LEND = "Lend"
    BORROW = "Borrow"


@dataclass
class Position:
    ticker: str
    name: str
    asset_class: AssetClass
    quantity: int
    market_price: float
    currency: str = "CAD"
    available_to_lend: float = 1.0

    @property
    def market_value(self) -> float:
        return self.quantity * self.market_price

    @property
    def lendable_value(self) -> float:
        return self.market_value * self.available_to_lend

    @property
    def lendable_quantity(self) -> int:
        return int(self.quantity * self.available_to_lend)


@dataclass
class SBLTransaction:
    transaction_id: str
    direction: LoanDirection
    counterparty: str
    position: Position
    quantity: int
    rate: float
    collateral_type: CollateralType
    trade_date: date
    settlement_date: date
    term_days: int = 1
    status: SettlementStatus = SettlementStatus.PENDING
    fail_reason: str = ""

    @property
    def notional_value(self) -> float:
        return self.quantity * self.position.market_price

    @property
    def required_collateral(self) -> float:
        return self.notional_value * 1.02

    @property
    def daily_fee(self) -> float:
        return self.notional_value * self.rate / 360

    @property
    def days_to_settlement(self) -> int:
        return (self.settlement_date - date.today()).days


@dataclass
class CollateralExposure:
    counterparty: str
    total_lent_value: float
    total_collateral_received: float
    coverage_ratio: float
    open_transactions: int
    failed_settlements: int

    @property
    def is_undercollateralized(self) -> bool:
        return self.coverage_ratio < 1.02
