"""Value types for broker connectivity.

Pure data — no I/O, no MT5 dependency. Consumed by the adapter interface
and the rest of scalping_core.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


class ConnectionStatus(str, Enum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTED = "CONNECTED"
    ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class AccountInfo:
    login: int
    server: str
    currency: str
    balance: Decimal
    equity: Decimal
    margin_free: Decimal
    account_type: str  # 'demo' or 'live'
    leverage: int
    company: str


@dataclass(frozen=True, slots=True)
class ContractSpec:
    """Per-symbol contract specification as discovered from the broker.

    All numeric fields use Decimal for exact representation.
    Fields mirror §5.2 of the master plan.
    """
    broker_symbol: str
    digits: int
    point: Decimal
    tick_size: Decimal
    tick_value: Decimal
    contract_size: Decimal
    volume_min: Decimal
    volume_max: Decimal
    volume_step: Decimal
    min_stop_distance: Decimal
    trade_allowed: bool
    margin_initial: Decimal | None
    commission_per_lot: Decimal | None
    swap_long: Decimal | None
    swap_short: Decimal | None


@dataclass(frozen=True, slots=True)
class Tick:
    """Single price update from the broker."""
    broker_symbol: str
    bid: Decimal
    ask: Decimal
    server_time_ms: int   # Broker server time, ms since Unix epoch
    recv_time_mono: float  # time.monotonic() at Python receipt
    is_newest: bool = True  # False for historical ticks within a batch


@dataclass(frozen=True, slots=True)
class SymbolMapping:
    """Maps a broker-specific symbol name to a canonical pair."""
    canonical_pair: str  # e.g. "EURUSD"
    broker_symbol: str   # e.g. "EURUSD_"
    contract: ContractSpec
