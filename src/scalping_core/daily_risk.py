"""Daily risk state machine.

Pure logic: P/L thresholds, sticky locks, Asia/Amman reset boundary.
No I/O, no database, no network.  Produces the RiskState that
risk_gate.evaluate_entry consumes.

Assumptions documented as ASSUMPTION comments below.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo
from uuid import uuid4

from .broker_types import ContractSpec
from .order_types import RiskEvent, RiskEventType
from .risk_gate import RiskState


def _require_finite_decimal(name: str, value: object) -> None:
    """Reject NaN, Infinity, and non-Decimal values.  Fail-closed."""
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be Decimal, got {type(value).__name__}")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite, got {value!r}")

AMMAN_TZ = ZoneInfo("Asia/Amman")
DEFAULT_PROFIT_LIMIT_USD = Decimal("15")
DEFAULT_LOSS_LIMIT_USD = Decimal("5")

_STICKY_STATES = frozenset(
    {RiskState.PROFIT_LOCKED, RiskState.LOSS_LOCKED, RiskState.DRAINING, RiskState.DISABLED}
)


@dataclass(frozen=True, slots=True)
class DailyRiskConfig:
    """Configurable daily thresholds.  Both limits are positive magnitudes."""

    profit_limit_usd: Decimal = DEFAULT_PROFIT_LIMIT_USD
    loss_limit_usd: Decimal = DEFAULT_LOSS_LIMIT_USD

    def __post_init__(self) -> None:
        _require_finite_decimal("profit_limit_usd", self.profit_limit_usd)
        _require_finite_decimal("loss_limit_usd", self.loss_limit_usd)
        if self.profit_limit_usd <= 0:
            raise ValueError("profit_limit_usd must be positive")
        if self.loss_limit_usd <= 0:
            raise ValueError("loss_limit_usd must be positive")


# ASSUMPTION: All monetary components use natural signs — profit positive,
# cost/loss negative — consistent with MT5 convention.  The caller is
# responsible for currency conversion to USD and for avoiding double-counting
# commissions already embedded in realized P/L.
@dataclass(frozen=True, slots=True)
class DailyPnL:
    """Daily P/L components.  All values in USD with natural signs."""

    realized_pnl_usd: Decimal
    floating_pnl_usd: Decimal
    commission_usd: Decimal  # negative = cost
    swap_usd: Decimal  # positive = credit, negative = debit

    def __post_init__(self) -> None:
        _require_finite_decimal("realized_pnl_usd", self.realized_pnl_usd)
        _require_finite_decimal("floating_pnl_usd", self.floating_pnl_usd)
        _require_finite_decimal("commission_usd", self.commission_usd)
        _require_finite_decimal("swap_usd", self.swap_usd)

    @property
    def net_pnl_usd(self) -> Decimal:
        return (
            self.realized_pnl_usd
            + self.floating_pnl_usd
            + self.commission_usd
            + self.swap_usd
        )


ZERO_PNL = DailyPnL(Decimal(0), Decimal(0), Decimal(0), Decimal(0))


def trading_day(utc_now: datetime) -> date:
    """Return the current trading day using the Asia/Amman boundary.

    The trading day rolls over at 00:00 Asia/Amman.  The exact UTC offset
    is determined by the IANA timezone database at runtime via
    ``ZoneInfo("Asia/Amman")``.

    *utc_now* must be timezone-aware.
    """
    if utc_now.tzinfo is None or utc_now.tzinfo.utcoffset(utc_now) is None:
        raise ValueError("utc_now must be timezone-aware")
    return utc_now.astimezone(AMMAN_TZ).date()


def is_new_trading_day(current_day: date, utc_now: datetime) -> bool:
    """True when *utc_now* falls in a later trading day than *current_day*."""
    return trading_day(utc_now) > current_day


def evaluate_state(
    state: RiskState,
    pnl: DailyPnL,
    config: DailyRiskConfig,
) -> RiskState:
    """Pure state transition: current state × net P/L → next state.

    Profit/loss locks are sticky and do not revert to ACTIVE from P/L movement
    alone.  DRAINING is a manual mode that blocks new entries and continues
    position management; it does not activate from P/L.  DISABLED persists
    until authorized manual reactivation.  Both survive daily rollover.

    When net P/L crosses both limits simultaneously (extreme floating
    swing), profit lock takes precedence.
    """
    if state in _STICKY_STATES:
        return state

    net = pnl.net_pnl_usd
    if not net.is_finite():
        return RiskState.LOSS_LOCKED
    if net >= config.profit_limit_usd:
        return RiskState.PROFIT_LOCKED
    if net <= -config.loss_limit_usd:
        return RiskState.LOSS_LOCKED
    return RiskState.ACTIVE


def reset_state(
    previous_state: RiskState,
    current_day: date,
    utc_now: datetime,
) -> RiskState:
    """Apply the Asia/Amman daily rollover without clearing manual stop modes.

    PROFIT_LOCKED and LOSS_LOCKED return to ACTIVE only after a verified new
    trading day.  DRAINING persists across rollover until an authorized
    operator clears it (approved decision #1).  DISABLED persists across
    rollovers and requires authorized manual reactivation (approved
    decision #2).  Before the boundary, a reset attempt fails closed as
    LOSS_LOCKED.  Invalid state input fails closed as DISABLED.
    """
    if not isinstance(previous_state, RiskState):
        return RiskState.DISABLED
    if previous_state in {RiskState.DRAINING, RiskState.DISABLED}:
        return previous_state
    if not is_new_trading_day(current_day, utc_now):
        return RiskState.LOSS_LOCKED
    return RiskState.ACTIVE


def operator_transition(
    state: RiskState, target: RiskState, *, account_id: str,
    operator_id: str | None, at: datetime,
) -> tuple[RiskState, RiskEvent]:
    """Apply an auditable operator-only state transition.

    The caller must persist the returned event and risk state atomically.
    This pure helper does not claim that an operator identity was
    authenticated; authorization remains the caller's responsibility.
    """
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("operator transition timestamp must be timezone-aware")
    if not account_id or not operator_id or not operator_id.strip():
        raise ValueError("account_id and operator_id are required")
    allowed = (
        state is RiskState.ACTIVE and target in {RiskState.DRAINING, RiskState.DISABLED}
    ) or (
        state in {RiskState.DRAINING, RiskState.DISABLED,
                  RiskState.PROFIT_LOCKED, RiskState.LOSS_LOCKED}
        and target is RiskState.ACTIVE
    )
    if not allowed:
        raise ValueError(f"operator transition {state.value} -> {target.value} is not permitted")
    event = RiskEvent(
        event_id=uuid4(), account_id=account_id,
        event_type=RiskEventType.LOCK_RESET if target is RiskState.ACTIVE
        else RiskEventType.LOCK_ACTIVATED,
        detail=f"daily risk state changed {state.value} -> {target.value}",
        related_intent_id=None, related_position_id=None,
        operator_id=operator_id, created_at=at,
    )
    return target, event


def calculate_floating_pnl_usd(
    *, side: object, entry_price: Decimal, current_bid: Decimal,
    current_ask: Decimal, lot_size: Decimal, contract: ContractSpec,
    account_to_usd_rate: Decimal | None,
) -> Decimal:
    """Mark an open position at the exit-side quote using contract tick value.

    Commissions and swaps remain separate daily P/L components to avoid
    double-counting. Currency conversion must be supplied by its owner-
    approved source; this function never invents one.
    """
    from .order_types import OrderSide

    values = (entry_price, current_bid, current_ask, lot_size,
              contract.tick_size, contract.tick_value)
    if any(not isinstance(value, Decimal) or not value.is_finite() for value in values):
        raise ValueError("floating P/L inputs must be finite Decimals")
    if current_bid <= 0 or current_ask < current_bid or entry_price <= 0 or lot_size <= 0:
        raise ValueError("floating P/L quote, entry, or volume is invalid")
    if contract.tick_size <= 0 or contract.tick_value <= 0:
        raise ValueError("contract tick value and size must be positive")
    if (account_to_usd_rate is None or not isinstance(account_to_usd_rate, Decimal)
            or not account_to_usd_rate.is_finite() or account_to_usd_rate <= 0):
        raise ValueError("account currency conversion is unavailable or invalid")
    mark = current_bid if side is OrderSide.BUY else current_ask if side is OrderSide.SELL else None
    if mark is None:
        raise ValueError("position side must be BUY or SELL")
    move_in_ticks = (mark - entry_price) / contract.tick_size
    if side is OrderSide.SELL:
        move_in_ticks = -move_in_ticks
    return move_in_ticks * contract.tick_value * lot_size * account_to_usd_rate


class DailyRiskController:
    """Persist daily P/L snapshots and state transitions through a store."""

    def __init__(self, store: object, config: DailyRiskConfig | None = None) -> None:
        self._store = store
        self._config = config or DailyRiskConfig()

    def update_pnl(
        self, *, account_id: str, trading_day: date, current_state: RiskState,
        pnl: DailyPnL, at: datetime,
    ) -> RiskState:
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError("risk update timestamp must be timezone-aware")
        next_state = evaluate_state(current_state, pnl, self._config)
        if next_state is current_state:
            self._store.save_risk_snapshot(trading_day, next_state, pnl)
            return next_state
        event = RiskEvent(
            event_id=uuid4(), account_id=account_id,
            event_type=RiskEventType.LIMIT_TRIGGERED,
            detail=f"daily net P/L {pnl.net_pnl_usd} changed state {current_state.value} -> {next_state.value}",
            related_intent_id=None, related_position_id=None,
            operator_id=None, created_at=at,
        )
        self._store.save_risk_transition(trading_day, next_state, pnl, event)
        # FR-008: cancel local DRAFT/PENDING_SUBMIT intents on limit trigger
        if hasattr(self._store, "cancel_cancellable_orders"):
            self._store.cancel_cancellable_orders()
        return next_state

    def apply_operator_action(
        self, *, account_id: str, trading_day: date, current_state: RiskState,
        target_state: RiskState, pnl: DailyPnL, operator_id: str | None,
        at: datetime,
    ) -> RiskState:
        next_state, event = operator_transition(
            current_state, target_state, account_id=account_id,
            operator_id=operator_id, at=at,
        )
        self._store.save_risk_transition(trading_day, next_state, pnl, event)
        return next_state
