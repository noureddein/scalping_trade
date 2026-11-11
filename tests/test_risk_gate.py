"""Tests for scalping_core.risk_gate — entry safety gate.

Covers every denial reason, the happy-path approval, boundary values,
and fail-closed behavior for non-finite numeric inputs.
No I/O, no broker, no database.
"""
from __future__ import annotations

from decimal import Decimal
import pytest

from scalping_core.risk_gate import (
    FIXED_LOT_SIZE,
    MAX_INTENDED_LOSS_USD,
    REQUIRED_SPREAD_STABILITY_SECONDS,
    EntryCheck,
    EntryDecision,
    RiskState,
    evaluate_entry,
)


def _ok_check(**overrides) -> EntryCheck:
    """Baseline check that should be approved — override one field to test denial."""
    defaults = dict(
        canonical_pair="EURUSD",
        volume_lots=FIXED_LOT_SIZE,
        risk_state=RiskState.ACTIVE,
        backend_available=True,
        broker_connected=True,
        risk_state_age_seconds=Decimal("1"),
        max_risk_state_age_seconds=Decimal("10"),
        market_data_fresh=True,
        trading_enabled=True,
        manual_spread_ok=True,
        adaptive_spread_ok=True,
        stable_spread_seconds=Decimal("120"),
        has_open_position=False,
        has_pending_entry=False,
        estimated_loss_usd=Decimal("0.30"),
        loss_estimate_valid=True,
    )
    defaults.update(overrides)
    return EntryCheck(**defaults)


class TestHappyPath:
    def test_all_conditions_met(self):
        d = evaluate_entry(_ok_check())
        assert d.approved is True
        assert d.reasons == ()

    def test_loss_at_exact_ceiling(self):
        d = evaluate_entry(_ok_check(estimated_loss_usd=MAX_INTENDED_LOSS_USD))
        assert d.approved is True

    def test_spread_at_exact_60s(self):
        d = evaluate_entry(_ok_check(stable_spread_seconds=REQUIRED_SPREAD_STABILITY_SECONDS))
        assert d.approved is True

    def test_risk_state_age_at_exact_max(self):
        d = evaluate_entry(_ok_check(
            risk_state_age_seconds=Decimal("10"),
            max_risk_state_age_seconds=Decimal("10"),
        ))
        assert d.approved is True

    def test_zero_loss_estimate(self):
        d = evaluate_entry(_ok_check(estimated_loss_usd=Decimal("0")))
        assert d.approved is True


class TestCanonicalPairValidation:
    @pytest.mark.parametrize("pair,reason", [
        ("eurusd", "canonical_pair_must_be_six_uppercase_letters"),
        ("EUR", "canonical_pair_must_be_six_uppercase_letters"),
        ("EURUSDJPY", "canonical_pair_must_be_six_uppercase_letters"),
        ("EUR123", "canonical_pair_must_be_six_uppercase_letters"),
        ("", "canonical_pair_must_be_six_uppercase_letters"),
        ("XAUUSD", "non_forex_instrument"),
        ("USDXAG", "non_forex_instrument"),
        ("XPTXPD", "non_forex_instrument"),
        ("EUREUR", "base_and_quote_currency_must_differ"),
        ("USDUSD", "base_and_quote_currency_must_differ"),
    ])
    def test_invalid_pairs(self, pair, reason):
        d = evaluate_entry(_ok_check(canonical_pair=pair))
        assert not d.approved
        assert reason in d.reasons

    def test_valid_forex_pairs(self):
        for pair in ("EURUSD", "GBPJPY", "AUDZAR", "NZDUSD"):
            d = evaluate_entry(_ok_check(canonical_pair=pair))
            assert d.approved, f"{pair} should be valid"


class TestVolume:
    def test_wrong_volume_denied(self):
        d = evaluate_entry(_ok_check(volume_lots=Decimal("0.02")))
        assert "volume_must_equal_fixed_0_01_lot" in d.reasons

    def test_zero_volume_denied(self):
        d = evaluate_entry(_ok_check(volume_lots=Decimal("0")))
        assert "volume_must_equal_fixed_0_01_lot" in d.reasons

    def test_exact_fixed_lot(self):
        d = evaluate_entry(_ok_check(volume_lots=Decimal("0.01")))
        assert "volume_must_equal_fixed_0_01_lot" not in d.reasons


class TestBackendAvailability:
    def test_backend_unavailable(self):
        d = evaluate_entry(_ok_check(backend_available=False))
        assert not d.approved
        assert "risk_authority_unavailable" in d.reasons


class TestBrokerConnected:
    def test_broker_not_connected(self):
        d = evaluate_entry(_ok_check(broker_connected=False))
        assert not d.approved
        assert "broker_not_connected" in d.reasons

    def test_broker_connected(self):
        d = evaluate_entry(_ok_check(broker_connected=True))
        assert "broker_not_connected" not in d.reasons

    def test_broker_and_backend_independent(self):
        d = evaluate_entry(_ok_check(backend_available=False, broker_connected=False))
        assert "risk_authority_unavailable" in d.reasons
        assert "broker_not_connected" in d.reasons


class TestRiskState:
    def test_none_state_denied(self):
        d = evaluate_entry(_ok_check(risk_state=None))
        assert "risk_state_unavailable" in d.reasons

    @pytest.mark.parametrize("state", [
        RiskState.PROFIT_LOCKED,
        RiskState.LOSS_LOCKED,
        RiskState.DRAINING,
        RiskState.DISABLED,
    ])
    def test_non_active_states_denied(self, state):
        d = evaluate_entry(_ok_check(risk_state=state))
        assert not d.approved
        assert "risk_state_not_active" in d.reasons


class TestRiskStateAge:
    def test_age_unknown(self):
        d = evaluate_entry(_ok_check(risk_state_age_seconds=None))
        assert "risk_state_age_unknown" in d.reasons

    def test_negative_age(self):
        d = evaluate_entry(_ok_check(risk_state_age_seconds=Decimal("-1")))
        assert "risk_state_age_invalid" in d.reasons

    def test_negative_max_age(self):
        d = evaluate_entry(_ok_check(max_risk_state_age_seconds=Decimal("-1")))
        assert "risk_state_max_age_invalid" in d.reasons

    def test_stale_state(self):
        d = evaluate_entry(_ok_check(
            risk_state_age_seconds=Decimal("11"),
            max_risk_state_age_seconds=Decimal("10"),
        ))
        assert "risk_state_stale" in d.reasons

    def test_just_within_max_age(self):
        d = evaluate_entry(_ok_check(
            risk_state_age_seconds=Decimal("10"),
            max_risk_state_age_seconds=Decimal("10"),
        ))
        assert "risk_state_stale" not in d.reasons


class TestMarketData:
    def test_stale_market_data(self):
        d = evaluate_entry(_ok_check(market_data_fresh=False))
        assert "market_data_stale" in d.reasons


class TestTradingEnabled:
    def test_pair_trading_disabled(self):
        d = evaluate_entry(_ok_check(trading_enabled=False))
        assert "pair_trading_disabled" in d.reasons


class TestSpread:
    def test_manual_spread_exceeded(self):
        d = evaluate_entry(_ok_check(manual_spread_ok=False))
        assert "manual_spread_limit_exceeded" in d.reasons

    def test_adaptive_spread_exceeded(self):
        d = evaluate_entry(_ok_check(adaptive_spread_ok=False))
        assert "adaptive_spread_limit_exceeded" in d.reasons

    def test_insufficient_stability(self):
        d = evaluate_entry(_ok_check(stable_spread_seconds=Decimal("59.99")))
        assert "spread_not_stable_for_required_60_seconds" in d.reasons

    def test_zero_stability(self):
        d = evaluate_entry(_ok_check(stable_spread_seconds=Decimal("0")))
        assert "spread_not_stable_for_required_60_seconds" in d.reasons


class TestPositionAndPending:
    def test_open_position_denied(self):
        d = evaluate_entry(_ok_check(has_open_position=True))
        assert "canonical_pair_already_has_open_position" in d.reasons

    def test_pending_entry_denied(self):
        d = evaluate_entry(_ok_check(has_pending_entry=True))
        assert "canonical_pair_already_has_pending_entry" in d.reasons


class TestLossEstimate:
    def test_invalid_estimate(self):
        d = evaluate_entry(_ok_check(loss_estimate_valid=False))
        assert "usd_loss_estimate_unavailable_or_invalid" in d.reasons

    def test_none_estimate(self):
        d = evaluate_entry(_ok_check(estimated_loss_usd=None))
        assert "usd_loss_estimate_unavailable_or_invalid" in d.reasons

    def test_negative_estimate(self):
        d = evaluate_entry(_ok_check(estimated_loss_usd=Decimal("-0.10")))
        assert "usd_loss_estimate_invalid" in d.reasons

    def test_exceeds_ceiling(self):
        d = evaluate_entry(_ok_check(estimated_loss_usd=Decimal("0.51")))
        assert "estimated_loss_exceeds_intended_0_50_usd_loss_ceiling" in d.reasons

    def test_at_ceiling_approved(self):
        d = evaluate_entry(_ok_check(estimated_loss_usd=Decimal("0.50")))
        assert "estimated_loss_exceeds_intended_0_50_usd_loss_ceiling" not in d.reasons

    def test_just_above_ceiling(self):
        d = evaluate_entry(_ok_check(estimated_loss_usd=Decimal("0.500001")))
        assert "estimated_loss_exceeds_intended_0_50_usd_loss_ceiling" in d.reasons


class TestNonFiniteNumericInputs:
    """Fail-closed: NaN, Infinity, sNaN, and -Infinity must never produce approved=True."""

    @pytest.mark.parametrize("field", [
        "volume_lots",
        "risk_state_age_seconds",
        "max_risk_state_age_seconds",
        "stable_spread_seconds",
        "estimated_loss_usd",
    ])
    @pytest.mark.parametrize("value", [
        Decimal("NaN"), Decimal("sNaN"),
        Decimal("Infinity"), Decimal("-Infinity"),
        float("nan"), float("inf"), float("-inf"),
    ])
    def test_invalid_numeric_denied(self, field, value):
        d = evaluate_entry(_ok_check(**{field: value}))
        assert not d.approved, f"{field}={value!r} must not be approved"

    def test_nan_volume_denied_with_reason(self):
        d = evaluate_entry(_ok_check(volume_lots=Decimal("NaN")))
        assert "volume_must_equal_fixed_0_01_lot" in d.reasons

    def test_nan_age_denied_with_reason(self):
        d = evaluate_entry(_ok_check(risk_state_age_seconds=Decimal("NaN")))
        assert "risk_state_age_invalid" in d.reasons

    def test_nan_max_age_denied_with_reason(self):
        d = evaluate_entry(_ok_check(max_risk_state_age_seconds=Decimal("NaN")))
        assert "risk_state_max_age_invalid" in d.reasons

    def test_nan_spread_stability_denied_with_reason(self):
        d = evaluate_entry(_ok_check(stable_spread_seconds=Decimal("NaN")))
        assert "spread_not_stable_for_required_60_seconds" in d.reasons

    def test_nan_loss_estimate_denied_with_reason(self):
        d = evaluate_entry(_ok_check(estimated_loss_usd=Decimal("NaN")))
        assert "usd_loss_estimate_unavailable_or_invalid" in d.reasons

    def test_infinity_spread_stability_denied(self):
        # Infinity is non-finite → fail-closed denies it
        d = evaluate_entry(_ok_check(stable_spread_seconds=Decimal("Infinity")))
        assert not d.approved
        assert "spread_not_stable_for_required_60_seconds" in d.reasons


class TestMultipleFailures:
    def test_all_failures_collected(self):
        d = evaluate_entry(EntryCheck(
            canonical_pair="bad",
            volume_lots=Decimal("0.10"),
            risk_state=None,
            backend_available=False,
            broker_connected=False,
            risk_state_age_seconds=None,
            max_risk_state_age_seconds=Decimal("10"),
            market_data_fresh=False,
            trading_enabled=False,
            manual_spread_ok=False,
            adaptive_spread_ok=False,
            stable_spread_seconds=Decimal("0"),
            has_open_position=True,
            has_pending_entry=True,
            estimated_loss_usd=None,
            loss_estimate_valid=False,
        ))
        assert not d.approved
        assert len(d.reasons) >= 11

    def test_reasons_are_tuple(self):
        d = evaluate_entry(_ok_check(backend_available=False))
        assert isinstance(d.reasons, tuple)


class TestConstants:
    def test_fixed_lot_value(self):
        assert FIXED_LOT_SIZE == Decimal("0.01")

    def test_max_loss_value(self):
        assert MAX_INTENDED_LOSS_USD == Decimal("0.50")

    def test_spread_stability_value(self):
        assert REQUIRED_SPREAD_STABILITY_SECONDS == Decimal("60")


def test_unconfigured_spread_gate_is_denied():
    decision = evaluate_entry(_ok_check(spread_gate_eligible=False))
    assert not decision.approved
    assert "spread_gate_unconfigured_or_market_unhealthy" in decision.reasons
