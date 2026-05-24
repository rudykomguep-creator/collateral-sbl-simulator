"""
Margin Engine — calculates margin calls, substitutions, and close-outs.
This mirrors what a repo trader monitors intraday.
"""

from data_models import RepoTrade, MarginCall, LifecycleEvent, EventType, TradeStatus
from typing import Tuple


def check_margin(trade: RepoTrade, current_mv: float, day: int) -> Tuple[bool, MarginCall | None]:
    """
    Check if a margin call is triggered.
    Returns (is_triggered, MarginCall object or None).
    """
    shortfall = trade.shortfall(current_mv)
    coverage = trade.coverage_ratio(current_mv)
    threshold_amount = trade.cash_lent * trade.margin_threshold

    if shortfall > threshold_amount:
        mc = MarginCall(
            day=day,
            shortfall_amount=shortfall,
            coverage_ratio=coverage,
        )
        return True, mc

    return False, None


def resolve_margin_call(
    mc: MarginCall,
    resolution_type: str,  # "cash", "collateral", "default"
    trade: RepoTrade,
    day: int,
) -> LifecycleEvent:
    """
    Resolve a margin call via cash top-up, collateral substitution, or default.
    """
    mc.resolved = True
    mc.resolution = resolution_type

    if resolution_type == "cash":
        mc.resolution = "Client posted additional cash"
        return LifecycleEvent(
            day=day,
            event_type=EventType.MARGIN_MET,
            description=f"Margin call resolved — client posted ${mc.shortfall_amount:,.0f} cash",
            cash_flow=mc.shortfall_amount,
            trade_status=TradeStatus.OPEN,
        )

    elif resolution_type == "collateral":
        mc.resolution = "Collateral substitution"
        return LifecycleEvent(
            day=day,
            event_type=EventType.SUBSTITUTION,
            description=f"Margin call resolved — collateral substituted to cover ${mc.shortfall_amount:,.0f} shortfall",
            cash_flow=0,
            trade_status=TradeStatus.OPEN,
        )

    elif resolution_type == "default":
        mc.resolution = "Client defaulted — close-out initiated"
        trade.status = TradeStatus.DEFAULTED
        return LifecycleEvent(
            day=day,
            event_type=EventType.DEFAULT,
            description=f"Client failed to meet margin call of ${mc.shortfall_amount:,.0f} — close-out initiated",
            cash_flow=-mc.shortfall_amount,
            trade_status=TradeStatus.DEFAULTED,
        )

    raise ValueError(f"Unknown resolution type: {resolution_type}")


def calculate_close_out(trade: RepoTrade, current_mv: float) -> dict:
    """
    Calculate P&L and recovery on a defaulted trade close-out.
    MS sells the collateral to recover the cash lent.
    """
    recovery = current_mv * (1 - trade.collateral.haircut)
    loss = max(0, trade.cash_lent - recovery)
    gain = max(0, recovery - trade.cash_lent)

    return {
        "cash_lent": trade.cash_lent,
        "collateral_mv": current_mv,
        "recovery_amount": recovery,
        "loss": loss,
        "gain": gain,
        "net_pnl": gain - loss,
    }
