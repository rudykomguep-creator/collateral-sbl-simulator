"""
Repo Engine — simulates the full lifecycle of a repo trade day by day.
Handles: open, daily accrual, margin monitoring, roll, close-out.
"""

from datetime import date, timedelta
from typing import List
from data_models import (
    RepoTrade, Collateral, CollateralType,
    LifecycleEvent, EventType, TradeStatus
)
from margin_engine import check_margin, resolve_margin_call, calculate_close_out, MarginCall


def simulate_lifecycle(
    trade: RepoTrade,
    price_path: List[float],           # List of daily market values for collateral
    margin_response: List[str],        # Per-day: "cash", "collateral", "default", or "none"
    roll_on_maturity: bool = False,
    roll_rate: float = None,
    roll_days: int = None,
) -> List[LifecycleEvent]:
    """
    Simulate the full repo trade lifecycle.

    Args:
        trade: The RepoTrade object
        price_path: Daily collateral market values (length >= term_days)
        margin_response: How client responds to margin calls each day
        roll_on_maturity: Whether to roll the trade at maturity
        roll_rate: New repo rate if rolling
        roll_days: New term if rolling

    Returns:
        List of LifecycleEvent objects representing the full timeline
    """
    events: List[LifecycleEvent] = []
    margin_calls: List[MarginCall] = []

    # ── Day 0: Trade Opens ──────────────────────────────────────────────────
    events.append(LifecycleEvent(
        day=0,
        event_type=EventType.OPEN,
        description=(
            f"Trade opened — MS lends ${trade.cash_lent:,.0f} to {trade.client_name} "
            f"against ${trade.collateral.market_value:,.0f} of "
            f"{trade.collateral.collateral_type.value} "
            f"(haircut: {trade.collateral.haircut*100:.1f}%). "
            f"Rate: {trade.repo_rate*100:.3f}% | Term: {trade.term_days}d"
        ),
        cash_flow=-trade.cash_lent,   # MS pays out cash
        collateral_value=trade.collateral.market_value,
        trade_status=TradeStatus.OPEN,
    ))

    current_mv = trade.collateral.market_value
    active = True

    # ── Daily lifecycle loop ────────────────────────────────────────────────
    for day in range(1, trade.term_days + 1):
        if not active:
            break

        # Update collateral price
        if day - 1 < len(price_path):
            current_mv = price_path[day - 1]

        accrued_interest = trade.daily_interest * day
        coverage = trade.coverage_ratio(current_mv)

        # Check margin
        triggered, mc = check_margin(trade, current_mv, day)

        if triggered:
            trade.status = TradeStatus.MARGIN_CALL_PENDING
            margin_calls.append(mc)

            events.append(LifecycleEvent(
                day=day,
                event_type=EventType.MARGIN_CALL,
                description=(
                    f"⚠️ MARGIN CALL — Collateral MV dropped to ${current_mv:,.0f}. "
                    f"Coverage ratio: {coverage:.3f}x. "
                    f"Shortfall: ${mc.shortfall_amount:,.0f}"
                ),
                cash_flow=0,
                collateral_value=current_mv,
                trade_status=TradeStatus.MARGIN_CALL_PENDING,
            ))

            # Resolve margin call
            raw = margin_response[day - 1] if day - 1 < len(margin_response) else "cash"
            response = raw if raw in ("cash", "collateral", "default") else "cash"
            resolution_event = resolve_margin_call(mc, response, trade, day)
            events.append(resolution_event)

            if trade.status == TradeStatus.DEFAULTED:
                closeout = calculate_close_out(trade, current_mv)
                events.append(LifecycleEvent(
                    day=day,
                    event_type=EventType.DEFAULT,
                    description=(
                        f"🔴 CLOSE-OUT: MS sells collateral. "
                        f"Recovery: ${closeout['recovery_amount']:,.0f} | "
                        f"Net P&L: ${closeout['net_pnl']:+,.0f}"
                    ),
                    cash_flow=closeout["recovery_amount"],
                    collateral_value=current_mv,
                    trade_status=TradeStatus.DEFAULTED,
                ))
                active = False
                continue
            else:
                trade.status = TradeStatus.OPEN

        else:
            # Normal day — just accrue
            events.append(LifecycleEvent(
                day=day,
                event_type=EventType.OPEN,
                description=(
                    f"Day {day} — Collateral MV: ${current_mv:,.0f} | "
                    f"Coverage: {coverage:.3f}x | "
                    f"Accrued interest: ${accrued_interest:,.2f}"
                ),
                cash_flow=trade.daily_interest,
                collateral_value=current_mv,
                trade_status=TradeStatus.OPEN,
            ))

        # Maturity
        if day == trade.term_days and active:
            if roll_on_maturity and roll_rate and roll_days:
                trade.status = TradeStatus.ROLLED
                events.append(LifecycleEvent(
                    day=day,
                    event_type=EventType.ROLL,
                    description=(
                        f"🔄 TRADE ROLLED — New rate: {roll_rate*100:.3f}% | "
                        f"New term: {roll_days}d | "
                        f"Repurchase price reset to ${trade.cash_lent:,.0f}"
                    ),
                    cash_flow=0,
                    collateral_value=current_mv,
                    trade_status=TradeStatus.ROLLED,
                ))
            else:
                trade.status = TradeStatus.CLOSED
                events.append(LifecycleEvent(
                    day=day,
                    event_type=EventType.CLOSE,
                    description=(
                        f"✅ TRADE CLOSED — Client repays ${trade.repurchase_price:,.2f} "
                        f"(principal ${trade.cash_lent:,.0f} + interest ${trade.total_interest:,.2f})"
                    ),
                    cash_flow=trade.repurchase_price,
                    collateral_value=current_mv,
                    trade_status=TradeStatus.CLOSED,
                ))

    return events
