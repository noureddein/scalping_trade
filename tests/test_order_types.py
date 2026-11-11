"""Tests for order_types — value types and state predicates.

PREPARED — NOT YET RUN. Market-dependent tests deferred until market open.
"""
from decimal import Decimal

from scalping_core.order_types import (
    OrderResult,
    OrderSide,
    OrderState,
    PositionState,
    StaleOrderStateError,
    is_terminal,
    is_valid_transition,
)


def test_terminal_states():
    for state in (OrderState.FILLED, OrderState.REJECTED, OrderState.EXPIRED, OrderState.FAILED):
        assert is_terminal(state), f"{state} should be terminal"


def test_non_terminal_states():
    for state in (OrderState.PENDING_SUBMIT, OrderState.SUBMITTED, OrderState.UNKNOWN):
        assert not is_terminal(state), f"{state} should not be terminal"


def test_order_side_values():
    assert OrderSide.BUY.value == "BUY"
    assert OrderSide.SELL.value == "SELL"


def test_position_state_values():
    assert PositionState.OPEN.value == "OPEN"
    assert PositionState.CLOSED.value == "CLOSED"
    assert PositionState.CLOSE_PENDING.value == "CLOSE_PENDING"


def test_order_result_defaults():
    r = OrderResult(state=OrderState.PENDING_SUBMIT)
    assert r.broker_ticket is None
    assert r.fill_price is None
    assert r.reject_reason is None


# -- Transition matrix ---------------------------------------------------------

def test_valid_forward_transitions():
    assert is_valid_transition(OrderState.PENDING_SUBMIT, OrderState.SUBMITTED)
    assert is_valid_transition(OrderState.PENDING_SUBMIT, OrderState.FILLED)
    assert is_valid_transition(OrderState.PENDING_SUBMIT, OrderState.FAILED)
    assert is_valid_transition(OrderState.PENDING_SUBMIT, OrderState.UNKNOWN)
    assert is_valid_transition(OrderState.SUBMITTED, OrderState.FILLED)
    assert is_valid_transition(OrderState.SUBMITTED, OrderState.REJECTED)
    assert is_valid_transition(OrderState.SUBMITTED, OrderState.UNKNOWN)
    assert is_valid_transition(OrderState.UNKNOWN, OrderState.SUBMITTED)
    assert is_valid_transition(OrderState.UNKNOWN, OrderState.FILLED)
    assert is_valid_transition(OrderState.UNKNOWN, OrderState.REJECTED)


def test_same_state_always_valid():
    for state in OrderState:
        assert is_valid_transition(state, state)


def test_backward_transitions_blocked():
    assert not is_valid_transition(OrderState.SUBMITTED, OrderState.PENDING_SUBMIT)
    assert not is_valid_transition(OrderState.UNKNOWN, OrderState.PENDING_SUBMIT)
    assert not is_valid_transition(OrderState.UNKNOWN, OrderState.FAILED)
    assert not is_valid_transition(OrderState.SUBMITTED, OrderState.FAILED)


def test_terminal_transitions_blocked():
    for terminal in (OrderState.FILLED, OrderState.REJECTED, OrderState.EXPIRED, OrderState.FAILED):
        for target in OrderState:
            if target == terminal:
                continue
            assert not is_valid_transition(terminal, target), (
                f"{terminal.value} → {target.value} should be blocked"
            )


def test_stale_order_state_error_fields():
    err = StaleOrderStateError("key-1", OrderState.PENDING_SUBMIT, OrderState.FILLED)
    assert err.idempotency_key == "key-1"
    assert err.attempted == OrderState.PENDING_SUBMIT
    assert err.current == OrderState.FILLED
    assert "FILLED" in str(err) and "PENDING_SUBMIT" in str(err)
