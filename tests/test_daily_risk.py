"""Tests for scalping_core.daily_risk — daily risk state machine.

Covers state transitions, sticky locks, P/L aggregation, Asia/Amman reset,
fail-closed behavior, and input validation.
No I/O, no broker, no database.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import math
import pytest

from scalping_core.daily_risk import (
    AMMAN_TZ,
    DailyPnL,
    DailyRiskConfig,
    ZERO_PNL,
    evaluate_state,
    is_new_trading_day,
    reset_state,
    trading_day,
)
from scalping_core.risk_gate import RiskState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pnl(realized=0, floating=0, commission=0, swap=0) -> DailyPnL:
    return DailyPnL(
        Decimal(str(realized)),
        Decimal(str(floating)),
        Decimal(str(commission)),
        Decimal(str(swap)),
    )


DEFAULT_CONFIG = DailyRiskConfig()
UTC = timezone.utc


# ---------------------------------------------------------------------------
# DailyPnL
# ---------------------------------------------------------------------------

class TestDailyPnL:
    def test_net_aggregation(self):
        p = _pnl(realized=10, floating=-3, commission=-1, swap=0.5)
        assert p.net_pnl_usd == Decimal("6.5")

    def test_zero_pnl(self):
        assert ZERO_PNL.net_pnl_usd == Decimal("0")

    def test_rejects_nan(self):
        with pytest.raises(ValueError, match="finite"):
            _pnl(realized=float("nan"))

    def test_rejects_infinity(self):
        with pytest.raises(ValueError, match="finite"):
            DailyPnL(Decimal("Infinity"), Decimal(0), Decimal(0), Decimal(0))

    def test_rejects_neg_infinity(self):
        with pytest.raises(ValueError, match="finite"):
            DailyPnL(Decimal(0), Decimal("-Infinity"), Decimal(0), Decimal(0))

    def test_rejects_non_decimal(self):
        with pytest.raises(TypeError, match="Decimal"):
            DailyPnL(1.0, Decimal(0), Decimal(0), Decimal(0))  # type: ignore[arg-type]

    def test_frozen(self):
        with pytest.raises(AttributeError):
            ZERO_PNL.realized_pnl_usd = Decimal("1")  # type: ignore[misc]


# ---------------------------------------------------------------------------
# DailyRiskConfig
# ---------------------------------------------------------------------------

class TestDailyRiskConfig:
    def test_defaults(self):
        c = DailyRiskConfig()
        assert c.profit_limit_usd == Decimal("15")
        assert c.loss_limit_usd == Decimal("5")

    def test_custom_limits(self):
        c = DailyRiskConfig(Decimal("20"), Decimal("10"))
        assert c.profit_limit_usd == Decimal("20")

    def test_rejects_zero_profit(self):
        with pytest.raises(ValueError, match="positive"):
            DailyRiskConfig(profit_limit_usd=Decimal("0"))

    def test_rejects_negative_loss(self):
        with pytest.raises(ValueError, match="positive"):
            DailyRiskConfig(loss_limit_usd=Decimal("-1"))

    def test_rejects_nan(self):
        with pytest.raises(ValueError, match="finite"):
            DailyRiskConfig(profit_limit_usd=Decimal("NaN"))

    def test_rejects_infinity(self):
        with pytest.raises(ValueError, match="finite"):
            DailyRiskConfig(loss_limit_usd=Decimal("Infinity"))


# ---------------------------------------------------------------------------
# evaluate_state — transitions
# ---------------------------------------------------------------------------

class TestEvaluateStateTransitions:
    def test_active_stays_active_when_within_limits(self):
        s = evaluate_state(RiskState.ACTIVE, _pnl(realized=5), DEFAULT_CONFIG)
        assert s is RiskState.ACTIVE

    def test_profit_lock_at_threshold(self):
        s = evaluate_state(RiskState.ACTIVE, _pnl(realized=15), DEFAULT_CONFIG)
        assert s is RiskState.PROFIT_LOCKED

    def test_profit_lock_above_threshold(self):
        s = evaluate_state(RiskState.ACTIVE, _pnl(realized=20), DEFAULT_CONFIG)
        assert s is RiskState.PROFIT_LOCKED

    def test_loss_lock_at_threshold(self):
        s = evaluate_state(RiskState.ACTIVE, _pnl(realized=-5), DEFAULT_CONFIG)
        assert s is RiskState.LOSS_LOCKED

    def test_loss_lock_below_threshold(self):
        s = evaluate_state(RiskState.ACTIVE, _pnl(realized=-10), DEFAULT_CONFIG)
        assert s is RiskState.LOSS_LOCKED

    def test_just_under_profit_threshold(self):
        s = evaluate_state(RiskState.ACTIVE, _pnl(realized=14.99), DEFAULT_CONFIG)
        assert s is RiskState.ACTIVE

    def test_just_above_loss_threshold(self):
        s = evaluate_state(RiskState.ACTIVE, _pnl(realized=-4.99), DEFAULT_CONFIG)
        assert s is RiskState.ACTIVE

    def test_net_includes_all_components(self):
        # realized=12 + floating=2 + commission=-1 + swap=2 = net 15 → lock
        s = evaluate_state(RiskState.ACTIVE, _pnl(12, 2, -1, 2), DEFAULT_CONFIG)
        assert s is RiskState.PROFIT_LOCKED

    def test_both_thresholds_crossed_profit_wins(self):
        # This is an edge case: net is both >= profit and <= -loss
        # Only possible with custom config where profit < loss (unusual)
        cfg = DailyRiskConfig(Decimal("1"), Decimal("1"))
        # net = 1 → profit lock (checked first)
        s = evaluate_state(RiskState.ACTIVE, _pnl(realized=1), cfg)
        assert s is RiskState.PROFIT_LOCKED


class TestEvaluateStateStickyLocks:
    @pytest.mark.parametrize("state", [
        RiskState.PROFIT_LOCKED,
        RiskState.LOSS_LOCKED,
    ])
    def test_sticky_states_do_not_revert(self, state):
        # Even with net P/L that would normally be ACTIVE
        s = evaluate_state(state, _pnl(realized=0), DEFAULT_CONFIG)
        assert s is state

    def test_profit_locked_stays_even_when_pnl_drops(self):
        s = evaluate_state(RiskState.PROFIT_LOCKED, _pnl(realized=-10), DEFAULT_CONFIG)
        assert s is RiskState.PROFIT_LOCKED

    def test_loss_locked_stays_even_when_pnl_rises(self):
        s = evaluate_state(RiskState.LOSS_LOCKED, _pnl(realized=20), DEFAULT_CONFIG)
        assert s is RiskState.LOSS_LOCKED


class TestEvaluateStateFailClosed:
    def test_nan_net_pnl_triggers_loss_lock(self):
        # DailyPnL.__post_init__ rejects NaN, so the `not net.is_finite()`
        # guard in evaluate_state is defense-in-depth.  Exercise it by
        # bypassing __post_init__ via object.__setattr__ on a frozen dataclass.
        pnl = DailyPnL(Decimal(0), Decimal(0), Decimal(0), Decimal(0))
        # Bypass frozen to inject NaN into one component
        object.__setattr__(pnl, "realized_pnl_usd", Decimal("NaN"))
        s = evaluate_state(RiskState.ACTIVE, pnl, DEFAULT_CONFIG)
        assert s is RiskState.LOSS_LOCKED

    def test_infinity_net_pnl_triggers_loss_lock(self):
        pnl = DailyPnL(Decimal(0), Decimal(0), Decimal(0), Decimal(0))
        object.__setattr__(pnl, "realized_pnl_usd", Decimal("Infinity"))
        s = evaluate_state(RiskState.ACTIVE, pnl, DEFAULT_CONFIG)
        assert s is RiskState.LOSS_LOCKED

    def test_neg_infinity_net_pnl_triggers_loss_lock(self):
        pnl = DailyPnL(Decimal(0), Decimal(0), Decimal(0), Decimal(0))
        object.__setattr__(pnl, "realized_pnl_usd", Decimal("-Infinity"))
        s = evaluate_state(RiskState.ACTIVE, pnl, DEFAULT_CONFIG)
        assert s is RiskState.LOSS_LOCKED


# ---------------------------------------------------------------------------
# trading_day
# ---------------------------------------------------------------------------

class TestTradingDay:
    def test_amman_before_midnight(self):
        # Jordan is permanent UTC+3 (DST abolished).
        # 2026-01-15 20:59 UTC → 2026-01-15 23:59 Amman → still Jan 15
        dt = datetime(2026, 1, 15, 20, 59, tzinfo=UTC)
        assert trading_day(dt) == date(2026, 1, 15)

    def test_amman_at_midnight(self):
        # 2026-01-15 21:00 UTC → 2026-01-16 00:00 Amman → Jan 16
        dt = datetime(2026, 1, 15, 21, 0, tzinfo=UTC)
        assert trading_day(dt) == date(2026, 1, 16)

    def test_amman_after_midnight(self):
        # 2026-01-15 21:30 UTC → 2026-01-16 00:30 Amman → Jan 16
        dt = datetime(2026, 1, 15, 21, 30, tzinfo=UTC)
        assert trading_day(dt) == date(2026, 1, 16)

    def test_amman_summer_same_offset(self):
        # Permanent UTC+3 — summer and winter have same boundary
        # 2026-07-15 20:59 UTC → 2026-07-15 23:59 Amman → Jul 15
        dt = datetime(2026, 7, 15, 20, 59, tzinfo=UTC)
        assert trading_day(dt) == date(2026, 7, 15)

    def test_amman_summer_midnight(self):
        # 2026-07-15 21:00 UTC → 2026-07-16 00:00 Amman (UTC+3)
        dt = datetime(2026, 7, 15, 21, 0, tzinfo=UTC)
        assert trading_day(dt) == date(2026, 7, 16)

    def test_naive_datetime_rejected(self):
        with pytest.raises(ValueError, match="timezone-aware"):
            trading_day(datetime(2026, 1, 15, 12, 0))

    def test_accepts_non_utc_aware(self):
        # Pass an Amman-aware datetime directly
        dt = datetime(2026, 1, 15, 23, 59, tzinfo=AMMAN_TZ)
        assert trading_day(dt) == date(2026, 1, 15)


# ---------------------------------------------------------------------------
# is_new_trading_day
# ---------------------------------------------------------------------------

class TestIsNewTradingDay:
    def test_same_day(self):
        dt = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
        assert is_new_trading_day(date(2026, 1, 15), dt) is False

    def test_next_day(self):
        # 2026-01-15 22:00 UTC → Amman Jan 16 → new day relative to Jan 15
        dt = datetime(2026, 1, 15, 22, 0, tzinfo=UTC)
        assert is_new_trading_day(date(2026, 1, 15), dt) is True

    def test_future_current_day(self):
        # current_day is ahead of utc_now's trading day → not new
        dt = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
        assert is_new_trading_day(date(2026, 1, 16), dt) is False


# ---------------------------------------------------------------------------
# reset_state
# ---------------------------------------------------------------------------

class TestResetState:
    def test_valid_reset(self):
        dt = datetime(2026, 1, 15, 22, 0, tzinfo=UTC)  # Amman Jan 16
        assert reset_state(RiskState.PROFIT_LOCKED, date(2026, 1, 15), dt) is RiskState.ACTIVE

    def test_fail_closed_same_day(self):
        dt = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)  # Amman Jan 15
        assert reset_state(RiskState.LOSS_LOCKED, date(2026, 1, 15), dt) is RiskState.LOSS_LOCKED

    def test_fail_closed_past_day(self):
        # current_day is in the future — clock went backwards?
        dt = datetime(2026, 1, 14, 12, 0, tzinfo=UTC)  # Amman Jan 14
        assert reset_state(RiskState.PROFIT_LOCKED, date(2026, 1, 15), dt) is RiskState.LOSS_LOCKED

    def test_reset_boundary_consistent_with_trading_day(self):
        # Jordan is permanent UTC+3 (DST abolished). Midnight Amman = 21:00 UTC.
        # 2026-03-27 21:00 UTC → 2026-03-28 00:00 Amman → day advanced.
        dt = datetime(2026, 3, 27, 21, 0, tzinfo=UTC)
        assert reset_state(RiskState.PROFIT_LOCKED, date(2026, 3, 27), dt) is RiskState.ACTIVE


# ---------------------------------------------------------------------------
# Approved owner decisions #1 (DRAINING) and #2 (DISABLED)
# See PROJECT_DECISIONS.md — 2026-11-06
# ---------------------------------------------------------------------------


class TestApprovedDrainingPolicy:
    """Decision #1: DRAINING is manual, blocks new entries, continues position
    management, persists across daily rollover, cleared only by operator."""

    def test_draining_is_sticky_in_evaluate_state(self):
        s = evaluate_state(RiskState.DRAINING, _pnl(realized=0), DEFAULT_CONFIG)
        assert s is RiskState.DRAINING

    def test_draining_sticky_regardless_of_pnl(self):
        s = evaluate_state(RiskState.DRAINING, _pnl(realized=20), DEFAULT_CONFIG)
        assert s is RiskState.DRAINING

    def test_draining_not_triggered_by_profit(self):
        s = evaluate_state(RiskState.ACTIVE, _pnl(realized=15), DEFAULT_CONFIG)
        assert s is RiskState.PROFIT_LOCKED  # not DRAINING

    def test_draining_not_triggered_by_loss(self):
        s = evaluate_state(RiskState.ACTIVE, _pnl(realized=-5), DEFAULT_CONFIG)
        assert s is RiskState.LOSS_LOCKED  # not DRAINING

    def test_draining_survives_new_trading_day(self):
        dt = datetime(2026, 1, 15, 22, 0, tzinfo=UTC)
        assert reset_state(RiskState.DRAINING, date(2026, 1, 15), dt) is RiskState.DRAINING

    def test_draining_survives_same_day_reset(self):
        dt = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
        assert reset_state(RiskState.DRAINING, date(2026, 1, 15), dt) is RiskState.DRAINING


class TestApprovedDisabledPolicy:
    """Decision #2: DISABLED persists across daily rollovers, cleared only
    through authorized manual reactivation."""

    def test_disabled_is_sticky_in_evaluate_state(self):
        s = evaluate_state(RiskState.DISABLED, _pnl(realized=0), DEFAULT_CONFIG)
        assert s is RiskState.DISABLED

    def test_disabled_sticky_regardless_of_pnl(self):
        s = evaluate_state(RiskState.DISABLED, _pnl(realized=20), DEFAULT_CONFIG)
        assert s is RiskState.DISABLED

    def test_disabled_survives_new_trading_day(self):
        dt = datetime(2026, 1, 15, 22, 0, tzinfo=UTC)
        assert reset_state(RiskState.DISABLED, date(2026, 1, 15), dt) is RiskState.DISABLED

    def test_disabled_survives_same_day_reset(self):
        dt = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
        assert reset_state(RiskState.DISABLED, date(2026, 1, 15), dt) is RiskState.DISABLED

    def test_invalid_previous_state_fails_closed_to_disabled(self):
        dt = datetime(2026, 1, 15, 22, 0, tzinfo=UTC)
        assert reset_state(None, date(2026, 1, 15), dt) is RiskState.DISABLED
