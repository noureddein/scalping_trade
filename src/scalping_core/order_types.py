"""Order and position value types for Phase 5 execution.

Pure data — no I/O, no broker calls. Consumed by the execution engine,
order manager, and position manager.

All types are immutable (frozen dataclasses). State transitions happen
via new instances, never mutation.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderState(str, Enum):
    DRAFT = "DRAFT"
    PENDING_SUBMIT = "PENDING_SUBMIT"
    SUBMITTING = "SUBMITTING"
    SUBMITTED = "SUBMITTED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"
    OPERATOR_OVERRIDE = "OPERATOR_OVERRIDE"
    OPERATOR_RESOLVED = "OPERATOR_RESOLVED"


class OutcomeType(str, Enum):
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    TIMEOUT = "TIMEOUT"
    UNKNOWN = "UNKNOWN"


class ReservationStatus(str, Enum):
    HELD = "HELD"
    RELEASED = "RELEASED"


class PositionStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    SETTLING = "SETTLING"


class DailyRiskStateEnum(str, Enum):
    ACTIVE = "ACTIVE"
    PROFIT_LOCKED = "PROFIT_LOCKED"
    LOSS_LOCKED = "LOSS_LOCKED"
    DRAINING = "DRAINING"
    DISABLED = "DISABLED"


class RiskEventType(str, Enum):
    ENTRY_REJECTED = "ENTRY_REJECTED"
    LIMIT_TRIGGERED = "LIMIT_TRIGGERED"
    LOCK_ACTIVATED = "LOCK_ACTIVATED"
    LOCK_RESET = "LOCK_RESET"
    OPERATOR_RESOLUTION = "OPERATOR_RESOLUTION"
    BARRIER_HELD = "BARRIER_HELD"
    BARRIER_RELEASED = "BARRIER_RELEASED"
    RECONCILIATION_START = "RECONCILIATION_START"
    RECONCILIATION_COMPLETE = "RECONCILIATION_COMPLETE"
    FILL_PERSIST_FAILURE = "FILL_PERSIST_FAILURE"
    ADMISSION_HALTED = "ADMISSION_HALTED"


class BarrierStatus(str, Enum):
    HELD = "HELD"
    RELEASED = "RELEASED"


_TERMINAL_STATES = frozenset({
    OrderState.FILLED, OrderState.REJECTED,
    OrderState.EXPIRED, OrderState.FAILED, OrderState.CANCELLED,
    OrderState.OPERATOR_RESOLVED,
})

_BROKER_UNRESOLVED_STATES = frozenset({
    OrderState.DRAFT, OrderState.PENDING_SUBMIT, OrderState.SUBMITTING, OrderState.SUBMITTED,
    OrderState.UNKNOWN, OrderState.OPERATOR_OVERRIDE,
})


def is_terminal(state: OrderState) -> bool:
    return state in _TERMINAL_STATES


_ALLOWED_TRANSITIONS: dict[OrderState, frozenset[OrderState]] = {
    OrderState.DRAFT: frozenset({OrderState.PENDING_SUBMIT, OrderState.CANCELLED}),
    OrderState.PENDING_SUBMIT: frozenset({
        OrderState.SUBMITTED, OrderState.FILLED, OrderState.REJECTED,
        OrderState.EXPIRED, OrderState.FAILED, OrderState.UNKNOWN,
        OrderState.OPERATOR_OVERRIDE, OrderState.SUBMITTING, OrderState.CANCELLED,
    }),
    OrderState.SUBMITTING: frozenset({
        OrderState.SUBMITTED, OrderState.FILLED, OrderState.REJECTED,
        OrderState.CANCELLED, OrderState.UNKNOWN, OrderState.OPERATOR_RESOLVED,
    }),
    OrderState.SUBMITTED: frozenset({
        OrderState.FILLED, OrderState.REJECTED,
        OrderState.EXPIRED, OrderState.UNKNOWN, OrderState.CANCELLED,
    }),
    OrderState.UNKNOWN: frozenset({
        OrderState.SUBMITTED, OrderState.FILLED,
        OrderState.REJECTED, OrderState.EXPIRED, OrderState.CANCELLED,
        OrderState.OPERATOR_RESOLVED,
    }),
    OrderState.FILLED: frozenset(),
    OrderState.REJECTED: frozenset(),
    OrderState.EXPIRED: frozenset(),
    OrderState.FAILED: frozenset(),
    OrderState.OPERATOR_OVERRIDE: frozenset({
        OrderState.FILLED, OrderState.REJECTED, OrderState.EXPIRED,
        OrderState.OPERATOR_RESOLVED,
    }),
    OrderState.CANCELLED: frozenset(),
    OrderState.OPERATOR_RESOLVED: frozenset(),
}


def is_valid_transition(from_state: OrderState, to_state: OrderState) -> bool:
    if from_state == to_state:
        return True
    return to_state in _ALLOWED_TRANSITIONS.get(from_state, frozenset())


def _aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _positive(name: str, value: Decimal) -> None:
    if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
        raise ValueError(f"{name} must be a positive finite Decimal")


@dataclass(frozen=True, slots=True)
class OrderIntent:
    intent_id: UUID
    pair: str
    account_id: str
    direction: OrderSide
    lot_size: Decimal
    entry_price_ref: Decimal
    stop_loss_price: Decimal
    take_profit_price: Decimal
    estimated_loss: Decimal
    strategy_name: str
    signal_id: UUID
    state: OrderState
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if not self.pair or not self.account_id or not self.strategy_name:
            raise ValueError("pair, account_id, and strategy_name are required")
        if self.lot_size != Decimal("0.01"):
            raise ValueError("pilot lot_size must equal 0.01")
        for name in ("entry_price_ref", "stop_loss_price", "take_profit_price", "estimated_loss"):
            _positive(name, getattr(self, name))
        _aware("created_at", self.created_at)
        _aware("updated_at", self.updated_at)


@dataclass(frozen=True, slots=True)
class OrderOutcome:
    outcome_id: UUID
    intent_id: UUID
    broker_ticket: str | None
    fill_price: Decimal | None
    fill_time: datetime | None
    outcome_type: OutcomeType
    broker_error: str | None
    correlation_token: str | None
    recorded_at: datetime

    def __post_init__(self) -> None:
        _aware("recorded_at", self.recorded_at)
        if self.fill_time is not None:
            _aware("fill_time", self.fill_time)
        if self.fill_price is not None:
            _positive("fill_price", self.fill_price)


@dataclass(frozen=True, slots=True)
class PairReservation:
    reservation_id: UUID
    pair: str
    account_id: str
    intent_id: UUID
    status: ReservationStatus
    acquired_at: datetime
    released_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.pair or not self.account_id:
            raise ValueError("pair and account_id are required")
        _aware("acquired_at", self.acquired_at)
        if self.released_at is not None:
            _aware("released_at", self.released_at)


@dataclass(frozen=True, slots=True)
class Position:
    position_id: UUID
    pair: str
    account_id: str
    intent_id: UUID
    direction: OrderSide
    lot_size: Decimal
    entry_price: Decimal
    stop_loss: Decimal
    take_profit: Decimal
    status: PositionStatus
    entry_time: datetime
    exit_price: Decimal | None = None
    exit_time: datetime | None = None
    realized_pnl: Decimal | None = None
    commission: Decimal | None = None
    swap: Decimal | None = None

    def __post_init__(self) -> None:
        if not self.pair or not self.account_id:
            raise ValueError("pair and account_id are required")
        for name in ("lot_size", "entry_price", "stop_loss", "take_profit"):
            _positive(name, getattr(self, name))
        _aware("entry_time", self.entry_time)
        if self.exit_time is not None:
            _aware("exit_time", self.exit_time)


@dataclass(frozen=True, slots=True)
class DailyRiskState:
    risk_state_id: UUID
    account_id: str
    trading_day: date
    state: DailyRiskStateEnum
    realized_pnl: Decimal
    floating_pnl: Decimal
    commissions: Decimal
    swaps: Decimal
    net_pnl: Decimal
    profit_limit: Decimal
    loss_limit: Decimal
    state_changed_at: datetime
    locked_by: str | None = None

    def __post_init__(self) -> None:
        if not self.account_id:
            raise ValueError("account_id is required")
        for name in ("realized_pnl", "floating_pnl", "commissions", "swaps", "net_pnl"):
            value = getattr(self, name)
            if not isinstance(value, Decimal) or not value.is_finite():
                raise ValueError(f"{name} must be finite Decimal")
        _positive("profit_limit", self.profit_limit)
        _positive("loss_limit", self.loss_limit)
        _aware("state_changed_at", self.state_changed_at)


@dataclass(frozen=True, slots=True)
class RiskEvent:
    event_id: UUID
    account_id: str
    event_type: RiskEventType
    detail: str
    related_intent_id: UUID | None
    related_position_id: UUID | None
    operator_id: str | None
    created_at: datetime

    def __post_init__(self) -> None:
        if not self.account_id or not self.detail:
            raise ValueError("account_id and detail are required")
        _aware("created_at", self.created_at)


@dataclass(frozen=True, slots=True)
class ReconciliationBarrier:
    barrier_id: UUID
    account_id: str
    status: BarrierStatus
    reason: str
    held_at: datetime
    released_at: datetime | None = None
    resolved_by: str | None = None

    def __post_init__(self) -> None:
        if not self.account_id or not self.reason:
            raise ValueError("account_id and reason are required")
        _aware("held_at", self.held_at)
        if self.released_at is not None:
            _aware("released_at", self.released_at)


class StaleOrderStateError(Exception):
    """Raised when an order state update is blocked by the transition matrix."""
    def __init__(self, idempotency_key: str, attempted: OrderState, current: OrderState) -> None:
        self.idempotency_key = idempotency_key
        self.attempted = attempted
        self.current = current
        super().__init__(
            f"order {idempotency_key}: transition {current.value} → {attempted.value} blocked"
        )


class AccountMismatchError(Exception):
    """Raised when a second MT5 account tries to use a single-account database."""
    def __init__(self, registered: str, attempted: str) -> None:
        self.registered = registered
        self.attempted = attempted
        super().__init__(
            f"database bound to account {registered!r}, cannot use with {attempted!r}"
        )


class PositionState(str, Enum):
    OPEN = "OPEN"
    CLOSE_PENDING = "CLOSE_PENDING"
    CLOSED = "CLOSED"


@dataclass(frozen=True, slots=True)
class OrderRequest:
    """What we intend to submit. Immutable intent record."""
    canonical_pair: str
    broker_symbol: str
    side: OrderSide
    volume_lots: Decimal
    stop_loss_price: Decimal
    take_profit_price: Decimal | None
    idempotency_key: str
    signal_timestamp_ms: int
    fresh_quote_bid: Decimal
    fresh_quote_ask: Decimal
    fresh_quote_time_ms: int


@dataclass(frozen=True, slots=True)
class OrderResult:
    """What the broker returned after submission or query."""
    state: OrderState
    broker_ticket: int | None = None
    fill_price: Decimal | None = None
    fill_volume: Decimal | None = None
    fill_time_ms: int | None = None
    reject_reason: str | None = None
    broker_retcode: int | None = None
    raw_comment: str | None = None


@dataclass(frozen=True, slots=True)
class OrderRecord:
    """Full lifecycle record: request + latest known result."""
    request: OrderRequest
    result: OrderResult
    created_mono: float
    updated_mono: float


@dataclass(frozen=True, slots=True)
class OverrideAuditRecord:
    """Structured audit data for an operator override.

    Persisted atomically with the OPERATOR_OVERRIDE state change.
    Separate from the order row — preserves operator identity,
    rationale, and inspection evidence as a distinct durable artifact.

    operator_id is a label, NOT an authentication claim. The system
    currently has no operator authentication mechanism. See
    _OVERRIDE_DISABLED in operator_resolution.py.
    """
    idempotency_key: str
    operator_id: str
    reason: str
    broker_inspection_summary: str
    timestamp_utc: str


@dataclass(frozen=True, slots=True)
class PositionInfo:
    """Snapshot of a broker-reported open position."""
    broker_ticket: int
    canonical_pair: str
    broker_symbol: str
    side: OrderSide
    volume_lots: Decimal
    open_price: Decimal
    current_price: Decimal
    stop_loss: Decimal
    take_profit: Decimal | None
    floating_pnl_usd: Decimal
    open_time_ms: int
    swap_usd: Decimal
    commission_usd: Decimal
