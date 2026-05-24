"""
Unit tests — Margin Engine & Repo Lifecycle
"""

import pytest
from datetime import date
from data_models import (
    Collateral, CollateralType, RepoTrade, TradeStatus,
    EventType, LifecycleEvent
)
from margin_engine import check_margin, resolve_margin_call, calculate_close_out, MarginCall
from repo_engine import simulate_lifecycle


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def standard_collateral():
    return Collateral(
        collateral_type=CollateralType.MBS,
        face_value=10_000_000,
        market_value=9_800_000,
        haircut_override=0.05,
    )


@pytest.fixture
def standard_trade(standard_collateral):
    return RepoTrade(
        client_name="Test Counterparty",
        collateral=standard_collateral,
        cash_lent=9_000_000,
        repo_rate=0.053,
        start_date=date.today(),
        term_days=7,
        margin_threshold=0.02,
    )


# ── Collateral tests ──────────────────────────────────────────────────────────

class TestCollateral:

    def test_eligible_value_applies_haircut(self, standard_collateral):
        expected = 9_800_000 * (1 - 0.05)
        assert abs(standard_collateral.eligible_value - expected) < 1

    def test_standard_haircut_used_when_no_override(self):
        col = Collateral(CollateralType.TREASURY, 10_000_000, 10_000_000)
        assert col.haircut == 0.02

    def test_haircut_override_takes_precedence(self, standard_collateral):
        assert standard_collateral.haircut == 0.05

    def test_price_change_updates_market_value(self, standard_collateral):
        updated = standard_collateral.apply_price_change(-0.10)
        assert abs(updated.market_value - 9_800_000 * 0.90) < 1
        # Original unchanged
        assert standard_collateral.market_value == 9_800_000


# ── RepoTrade tests ───────────────────────────────────────────────────────────

class TestRepoTrade:

    def test_daily_interest(self, standard_trade):
        expected = 9_000_000 * 0.053 / 360
        assert abs(standard_trade.daily_interest - expected) < 0.01

    def test_total_interest(self, standard_trade):
        expected = standard_trade.daily_interest * 7
        assert abs(standard_trade.total_interest - expected) < 0.01

    def test_repurchase_price(self, standard_trade):
        expected = 9_000_000 + standard_trade.total_interest
        assert abs(standard_trade.repurchase_price - expected) < 0.01

    def test_coverage_ratio_above_one_when_collateral_sufficient(self, standard_trade):
        # MV 9.8M, haircut 5% → eligible 9.31M > cash lent 9M
        ratio = standard_trade.coverage_ratio(9_800_000)
        assert ratio > 1.0

    def test_coverage_ratio_below_one_when_collateral_drops(self, standard_trade):
        # MV drops to 8M → eligible 7.6M < cash lent 9M
        ratio = standard_trade.coverage_ratio(8_000_000)
        assert ratio < 1.0

    def test_shortfall_positive_when_undercollateralized(self, standard_trade):
        shortfall = standard_trade.shortfall(8_000_000)
        assert shortfall > 0

    def test_shortfall_negative_when_overcollateralized(self, standard_trade):
        shortfall = standard_trade.shortfall(9_800_000)
        assert shortfall < 0


# ── Margin call tests ─────────────────────────────────────────────────────────

class TestMarginEngine:

    def test_no_margin_call_when_collateral_sufficient(self, standard_trade):
        triggered, mc = check_margin(standard_trade, 9_800_000, day=1)
        assert triggered is False
        assert mc is None

    def test_margin_call_triggered_when_shortfall_exceeds_threshold(self, standard_trade):
        # Drop MV to 8M → shortfall ~1.4M >> 2% threshold (180k)
        triggered, mc = check_margin(standard_trade, 8_000_000, day=1)
        assert triggered is True
        assert mc is not None
        assert mc.shortfall_amount > 0

    def test_margin_call_threshold_is_respected(self, standard_trade):
        # Just below threshold — MV slightly above min coverage
        threshold_mv = standard_trade.cash_lent / (1 - standard_trade.collateral.haircut)
        just_above = threshold_mv * 1.005  # 0.5% above minimum
        triggered, _ = check_margin(standard_trade, just_above, day=1)
        assert triggered is False

    def test_resolve_cash_returns_correct_event(self, standard_trade):
        mc = MarginCall(day=2, shortfall_amount=500_000, coverage_ratio=0.94)
        event = resolve_margin_call(mc, "cash", standard_trade, day=2)
        assert event.event_type == EventType.MARGIN_MET
        assert event.cash_flow == 500_000
        assert mc.resolved is True

    def test_resolve_collateral_substitution(self, standard_trade):
        mc = MarginCall(day=2, shortfall_amount=300_000, coverage_ratio=0.96)
        event = resolve_margin_call(mc, "collateral", standard_trade, day=2)
        assert event.event_type == EventType.SUBSTITUTION
        assert event.cash_flow == 0

    def test_resolve_default_changes_trade_status(self, standard_trade):
        mc = MarginCall(day=3, shortfall_amount=1_000_000, coverage_ratio=0.88)
        event = resolve_margin_call(mc, "default", standard_trade, day=3)
        assert event.event_type == EventType.DEFAULT
        assert standard_trade.status == TradeStatus.DEFAULTED

    def test_close_out_recovery_calculation(self, standard_trade):
        result = calculate_close_out(standard_trade, current_mv=8_500_000)
        expected_recovery = 8_500_000 * (1 - 0.05)
        assert abs(result["recovery_amount"] - expected_recovery) < 1
        assert result["loss"] == max(0, standard_trade.cash_lent - expected_recovery)

    def test_close_out_no_loss_when_collateral_sufficient(self, standard_trade):
        # MV still high enough to cover cash lent
        result = calculate_close_out(standard_trade, current_mv=9_800_000)
        assert result["loss"] == 0
        assert result["gain"] > 0


# ── Lifecycle simulation tests ────────────────────────────────────────────────

class TestLifecycleSimulation:

    def test_first_event_is_trade_open(self, standard_trade):
        price_path = [9_800_000] * 7
        events = simulate_lifecycle(standard_trade, price_path, ["cash"] * 7)
        assert events[0].event_type == EventType.OPEN
        assert events[0].day == 0

    def test_last_event_is_trade_closed_on_normal_path(self, standard_trade):
        price_path = [9_800_000] * 7
        events = simulate_lifecycle(standard_trade, price_path, ["cash"] * 7)
        last = events[-1]
        assert last.event_type == EventType.CLOSE
        assert last.trade_status == TradeStatus.CLOSED

    def test_margin_call_appears_in_events_on_price_drop(self, standard_trade):
        price_path = [9_800_000, 9_800_000, 7_500_000, 7_500_000, 7_500_000, 7_500_000, 7_500_000]
        events = simulate_lifecycle(standard_trade, price_path, ["cash"] * 7)
        event_types = [e.event_type for e in events]
        assert EventType.MARGIN_CALL in event_types

    def test_default_stops_simulation(self, standard_trade):
        price_path = [9_800_000, 9_800_000, 7_000_000, 7_000_000, 7_000_000, 7_000_000, 7_000_000]
        events = simulate_lifecycle(standard_trade, price_path, ["default"] * 7)
        event_types = [e.event_type for e in events]
        assert EventType.DEFAULT in event_types
        # No CLOSE event after default
        assert EventType.CLOSE not in event_types

    def test_roll_produces_roll_event(self, standard_trade):
        price_path = [9_800_000] * 7
        events = simulate_lifecycle(
            standard_trade, price_path, ["cash"] * 7,
            roll_on_maturity=True, roll_rate=0.055, roll_days=7
        )
        event_types = [e.event_type for e in events]
        assert EventType.ROLL in event_types

    def test_repurchase_price_in_close_event(self, standard_trade):
        price_path = [9_800_000] * 7
        events = simulate_lifecycle(standard_trade, price_path, ["cash"] * 7)
        close_event = next(e for e in events if e.event_type == EventType.CLOSE)
        assert abs(close_event.cash_flow - standard_trade.repurchase_price) < 1

    def test_stable_price_produces_no_margin_calls(self, standard_trade):
        price_path = [9_800_000] * 7
        events = simulate_lifecycle(standard_trade, price_path, ["cash"] * 7)
        margin_calls = [e for e in events if e.event_type == EventType.MARGIN_CALL]
        assert len(margin_calls) == 0
