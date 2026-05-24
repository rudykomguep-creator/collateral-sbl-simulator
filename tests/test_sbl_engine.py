"""
Unit tests — SBL Engine & Settlement Tracking
"""

import pytest
from datetime import date, timedelta
from data_models import (
    Position, SBLTransaction, AssetClass, CollateralType,
    LoanDirection, SettlementStatus
)
from sbl_engine import (
    build_sample_portfolio, generate_sbl_transactions,
    compute_counterparty_exposures, settlement_summary
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_position():
    return Position(
        ticker="RY.TO",
        name="Royal Bank of Canada",
        asset_class=AssetClass.EQUITY,
        quantity=10_000,
        market_price=138.50,
        available_to_lend=0.80,
    )


@pytest.fixture
def sample_transaction(sample_position):
    today = date.today()
    return SBLTransaction(
        transaction_id="SBL-TEST-001",
        direction=LoanDirection.LEND,
        counterparty="Test Hedge Fund",
        position=sample_position,
        quantity=5_000,
        rate=0.025,
        collateral_type=CollateralType.TREASURY,
        trade_date=today,
        settlement_date=today + timedelta(days=2),
        term_days=1,
        status=SettlementStatus.PENDING,
    )


# ── Position tests ────────────────────────────────────────────────────────────

class TestPosition:

    def test_market_value(self, sample_position):
        expected = 10_000 * 138.50
        assert abs(sample_position.market_value - expected) < 0.01

    def test_lendable_value(self, sample_position):
        expected = sample_position.market_value * 0.80
        assert abs(sample_position.lendable_value - expected) < 0.01

    def test_lendable_quantity(self, sample_position):
        expected = int(10_000 * 0.80)
        assert sample_position.lendable_quantity == expected

    def test_fully_available_position(self):
        pos = Position("TEST", "Test", AssetClass.EQUITY, 1_000, 100.0, available_to_lend=1.0)
        assert pos.lendable_quantity == 1_000

    def test_zero_available_position(self):
        pos = Position("TEST", "Test", AssetClass.EQUITY, 1_000, 100.0, available_to_lend=0.0)
        assert pos.lendable_quantity == 0


# ── SBL Transaction tests ─────────────────────────────────────────────────────

class TestSBLTransaction:

    def test_notional_value(self, sample_transaction):
        expected = 5_000 * 138.50
        assert abs(sample_transaction.notional_value - expected) < 0.01

    def test_required_collateral_is_102_percent(self, sample_transaction):
        expected = sample_transaction.notional_value * 1.02
        assert abs(sample_transaction.required_collateral - expected) < 0.01

    def test_daily_fee(self, sample_transaction):
        expected = sample_transaction.notional_value * 0.025 / 360
        assert abs(sample_transaction.daily_fee - expected) < 0.001

    def test_required_collateral_always_exceeds_notional(self, sample_transaction):
        assert sample_transaction.required_collateral > sample_transaction.notional_value

    def test_settlement_date_in_future_for_pending(self, sample_transaction):
        assert sample_transaction.settlement_date >= date.today()


# ── Portfolio generation tests ────────────────────────────────────────────────

class TestPortfolio:

    def test_portfolio_has_correct_count(self):
        portfolio = build_sample_portfolio()
        assert len(portfolio) == 12

    def test_all_positions_have_positive_market_value(self):
        portfolio = build_sample_portfolio()
        for p in portfolio:
            assert p.market_value > 0

    def test_all_available_to_lend_between_0_and_1(self):
        portfolio = build_sample_portfolio()
        for p in portfolio:
            assert 0 <= p.available_to_lend <= 1.0

    def test_portfolio_contains_mixed_asset_classes(self):
        portfolio = build_sample_portfolio()
        asset_classes = {p.asset_class for p in portfolio}
        assert AssetClass.EQUITY in asset_classes
        assert AssetClass.GOVERNMENT_BOND in asset_classes

    def test_same_seed_produces_same_portfolio(self):
        p1 = build_sample_portfolio(seed=42)
        p2 = build_sample_portfolio(seed=42)
        for a, b in zip(p1, p2):
            assert a.available_to_lend == b.available_to_lend

    def test_different_seeds_produce_different_portfolios(self):
        p1 = build_sample_portfolio(seed=1)
        p2 = build_sample_portfolio(seed=2)
        atl_1 = [p.available_to_lend for p in p1]
        atl_2 = [p.available_to_lend for p in p2]
        assert atl_1 != atl_2


# ── Transaction generation tests ──────────────────────────────────────────────

class TestTransactionGeneration:

    def test_generates_correct_number_of_transactions(self):
        portfolio = build_sample_portfolio()
        txns = generate_sbl_transactions(portfolio, n_transactions=10)
        assert len(txns) == 10

    def test_all_transactions_have_positive_notional(self):
        portfolio = build_sample_portfolio()
        txns = generate_sbl_transactions(portfolio, n_transactions=15)
        for t in txns:
            assert t.notional_value > 0

    def test_all_required_collateral_is_102_percent(self):
        portfolio = build_sample_portfolio()
        txns = generate_sbl_transactions(portfolio, n_transactions=15)
        for t in txns:
            assert abs(t.required_collateral / t.notional_value - 1.02) < 0.001

    def test_fail_rate_zero_produces_no_failed_transactions(self):
        portfolio = build_sample_portfolio()
        txns = generate_sbl_transactions(portfolio, n_transactions=20, fail_rate=0.0)
        failed = [t for t in txns if t.status == SettlementStatus.FAILED]
        assert len(failed) == 0

    def test_all_transaction_ids_are_unique(self):
        portfolio = build_sample_portfolio()
        txns = generate_sbl_transactions(portfolio, n_transactions=20)
        ids = [t.transaction_id for t in txns]
        assert len(ids) == len(set(ids))

    def test_rates_are_positive(self):
        portfolio = build_sample_portfolio()
        txns = generate_sbl_transactions(portfolio, n_transactions=15)
        for t in txns:
            assert t.rate > 0


# ── Settlement summary tests ──────────────────────────────────────────────────

class TestSettlementSummary:

    def test_total_equals_sum_of_all_statuses(self):
        portfolio = build_sample_portfolio()
        txns = generate_sbl_transactions(portfolio, n_transactions=20)
        s = settlement_summary(txns)
        assert s["total"] == s["settled"] + s["failed"] + s["pending"] + s["partial"]

    def test_settlement_rate_between_0_and_1(self):
        portfolio = build_sample_portfolio()
        txns = generate_sbl_transactions(portfolio, n_transactions=20)
        s = settlement_summary(txns)
        assert 0 <= s["settlement_rate"] <= 1.0

    def test_total_notional_is_positive(self):
        portfolio = build_sample_portfolio()
        txns = generate_sbl_transactions(portfolio, n_transactions=20)
        s = settlement_summary(txns)
        assert s["total_notional"] > 0

    def test_empty_transaction_list(self):
        s = settlement_summary([])
        assert s["total"] == 0
        assert s["settlement_rate"] == 0


# ── Counterparty exposure tests ───────────────────────────────────────────────

class TestCounterpartyExposure:

    def test_exposures_generated_for_lending_transactions(self):
        portfolio = build_sample_portfolio()
        txns = generate_sbl_transactions(portfolio, n_transactions=20, fail_rate=0.0)
        exposures = compute_counterparty_exposures(txns)
        assert len(exposures) > 0

    def test_all_coverage_ratios_positive(self):
        portfolio = build_sample_portfolio()
        txns = generate_sbl_transactions(portfolio, n_transactions=20)
        exposures = compute_counterparty_exposures(txns)
        for e in exposures:
            assert e.coverage_ratio > 0

    def test_undercollateralized_flag_correct(self):
        portfolio = build_sample_portfolio()
        txns = generate_sbl_transactions(portfolio, n_transactions=20)
        exposures = compute_counterparty_exposures(txns)
        for e in exposures:
            if e.coverage_ratio < 1.02:
                assert e.is_undercollateralized is True
            else:
                assert e.is_undercollateralized is False

    def test_exposures_sorted_by_lent_value_descending(self):
        portfolio = build_sample_portfolio()
        txns = generate_sbl_transactions(portfolio, n_transactions=25)
        exposures = compute_counterparty_exposures(txns)
        lent_values = [e.total_lent_value for e in exposures]
        assert lent_values == sorted(lent_values, reverse=True)
