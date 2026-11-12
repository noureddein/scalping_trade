"""Stop-loss calculator (§10.2).

Computes the stop-loss price for a trade entry, enforcing:
  1. ATR-based stop distance (caller supplies ATR value).
  2. $0.50 maximum intended cash-loss ceiling.
  3. Broker minimum stop distance.

If the required stop distance cannot satisfy the $0.50 ceiling:
reject the trade. Never widen the stop to satisfy broker constraints.

The system documents that gaps, slippage, and execution failures may cause
actual losses to exceed the intended cap — this module computes the
*intended* stop, not a guarantee.

ATR computation is a market-data concern; this module receives it as input.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .broker_types import ContractSpec
from .order_types import OrderSide
from .risk_gate import MAX_INTENDED_LOSS_USD


@dataclass(frozen=True, slots=True)
class StopLossResult:
    approved: bool
    stop_price: Decimal | None = None
    stop_distance_points: Decimal | None = None
    estimated_loss_usd: Decimal | None = None
    reject_reason: str | None = None


_ZERO = Decimal(0)


def _require_finite(name: str, v: Decimal) -> str | None:
    if not isinstance(v, Decimal) or not v.is_finite():
        return f"{name}_not_finite"
    return None


def calculate_stop_loss(
    side: OrderSide,
    entry_price: Decimal,
    atr_points: Decimal,
    contract: ContractSpec,
    max_loss_usd: Decimal = MAX_INTENDED_LOSS_USD,
) -> StopLossResult:
    """Calculate stop-loss price from ATR, cash ceiling, and broker constraints.

    Returns StopLossResult with approved=False if the stop can't fit.
    """
    for name, val in [("entry_price", entry_price), ("atr_points", atr_points),
                       ("max_loss_usd", max_loss_usd)]:
        err = _require_finite(name, val)
        if err:
            return StopLossResult(approved=False, reject_reason=err)

    if entry_price <= 0:
        return StopLossResult(approved=False, reject_reason="entry_price_non_positive")
    if atr_points <= 0:
        return StopLossResult(approved=False, reject_reason="atr_non_positive")
    if max_loss_usd <= 0:
        return StopLossResult(approved=False, reject_reason="max_loss_non_positive")

    tick_value = contract.tick_value
    tick_size = contract.tick_size
    volume_min = contract.volume_min

    if tick_value <= 0 or tick_size <= 0 or volume_min <= 0:
        return StopLossResult(approved=False, reject_reason="contract_spec_invalid")

    loss_per_point = (tick_value / tick_size) * volume_min
    if loss_per_point <= 0:
        return StopLossResult(approved=False, reject_reason="loss_per_point_non_positive")

    # Preserve the strategy's requested distance. Never silently narrow it
    # to meet the cash ceiling or widen it to meet broker constraints.
    stop_distance = atr_points

    if contract.min_stop_distance > 0 and stop_distance < contract.min_stop_distance:
        cash_at_min_stop = loss_per_point * contract.min_stop_distance
        if cash_at_min_stop > max_loss_usd:
            return StopLossResult(
                approved=False,
                stop_distance_points=contract.min_stop_distance,
                estimated_loss_usd=cash_at_min_stop,
                reject_reason="broker_min_stop_exceeds_cash_ceiling",
            )
        return StopLossResult(
            approved=False, stop_distance_points=stop_distance,
            estimated_loss_usd=loss_per_point * stop_distance,
            reject_reason="stop_distance_below_broker_minimum",
        )

    estimated_loss = loss_per_point * stop_distance
    if estimated_loss > max_loss_usd:
        return StopLossResult(
            approved=False, stop_distance_points=stop_distance,
            estimated_loss_usd=estimated_loss,
            reject_reason="estimated_loss_exceeds_intended_0_50_usd_loss_ceiling",
        )

    if side == OrderSide.BUY:
        stop_price = entry_price - stop_distance
    else:
        stop_price = entry_price + stop_distance

    if stop_price <= 0:
        return StopLossResult(approved=False, reject_reason="stop_price_non_positive")

    return StopLossResult(
        approved=True,
        stop_price=stop_price,
        stop_distance_points=stop_distance,
        estimated_loss_usd=estimated_loss,
    )
