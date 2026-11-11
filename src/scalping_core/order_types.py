"""Order and position value types for Phase 5 execution.

Pure data — no I/O, no broker calls. Consumed by the execution engine,
order manager, and position manager.

All types are immutable (frozen dataclasses). State transitions happen
via new instances, never mutation.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderState(str, Enum):
    PENDING_SUBMIT = "PENDING_SUBMIT"
    SUBMITTED = "SUBMITTED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"
    OPERATOR_OVERRIDE = "OPERATOR_OVERRIDE"


_TERMINAL_STATES = frozenset({
    OrderState.FILLED, OrderState.REJECTED,
    OrderState.EXPIRED, OrderState.FAILED,
})

_BROKER_UNRESOLVED_STATES = frozenset({
    OrderState.PENDING_SUBMIT, OrderState.SUBMITTED,
    OrderState.UNKNOWN, OrderState.OPERATOR_OVERRIDE,
})


def is_terminal(state: OrderState) -> bool:
    return state in _TERMINAL_STATES


_ALLOWED_TRANSITIONS: dict[OrderState, frozenset[OrderState]] = {
    OrderState.PENDING_SUBMIT: frozenset({
        OrderState.SUBMITTED, OrderState.FILLED, OrderState.REJECTED,
        OrderState.EXPIRED, OrderState.FAILED, OrderState.UNKNOWN,
        OrderState.OPERATOR_OVERRIDE,
    }),
    OrderState.SUBMITTED: frozenset({
        OrderState.FILLED, OrderState.REJECTED,
        OrderState.EXPIRED, OrderState.UNKNOWN,
    }),
    OrderState.UNKNOWN: frozenset({
        OrderState.SUBMITTED, OrderState.FILLED,
        OrderState.REJECTED, OrderState.EXPIRED,
    }),
    OrderState.FILLED: frozenset(),
    OrderState.REJECTED: frozenset(),
    OrderState.EXPIRED: frozenset(),
    OrderState.FAILED: frozenset(),
    OrderState.OPERATOR_OVERRIDE: frozenset({
        OrderState.FILLED, OrderState.REJECTED, OrderState.EXPIRED,
    }),
}


def is_valid_transition(from_state: OrderState, to_state: OrderState) -> bool:
    if from_state == to_state:
        return True
    return to_state in _ALLOWED_TRANSITIONS.get(from_state, frozenset())


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
