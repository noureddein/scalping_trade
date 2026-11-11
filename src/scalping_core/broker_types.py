"""Value types for broker connectivity.

Pure data — no I/O, no MT5 dependency. Consumed by the adapter interface
and the rest of scalping_core.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum


class ConnectionStatus(str, Enum):
    DISCONNECTED = "DISCONNECTED"
    RECONNECTING = "RECONNECTING"
    CONNECTED = "CONNECTED"
    ERROR = "ERROR"


BrokerConnectionState = ConnectionStatus


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

    @property
    def account_number(self) -> int:
        return self.login

    @property
    def broker_name(self) -> str:
        return self.server

    @property
    def margin(self) -> Decimal:
        """Return the legacy margin_free value used by this wire protocol."""
        return self.margin_free


@dataclass(frozen=True, slots=True)
class BrokerSymbol:
    broker_name: str
    trading_permitted: bool
    account_number: int | None = None


@dataclass(frozen=True, slots=True)
class CanonicalSymbol:
    name: str
    is_forex: bool = True

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("canonical symbol name must not be empty")
        if not self.is_forex:
            raise ValueError("only Forex canonical symbols are supported")


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
    trading_permissions: str | None = None

    @property
    def eligible_for_trading(self) -> bool:
        return all(value is not None for value in (
            self.margin_initial, self.commission_per_lot,
            self.swap_long, self.swap_short, self.trading_permissions,
        ))

    @property
    def margin_requirement(self) -> Decimal | None:
        return self.margin_initial

    @property
    def commission(self) -> Decimal | None:
        return self.commission_per_lot


class TickValidationStatus(str, Enum):
    VALID = "VALID"
    CROSSED = "CROSSED"
    STALE = "STALE"
    DUPLICATE = "DUPLICATE"
    MALFORMED = "MALFORMED"
    REORDERED = "REORDERED"


@dataclass(frozen=True, slots=True)
class Tick:
    """Single price update, with legacy and Phase 3 timestamp fields."""
    broker_symbol: str = ""
    bid: Decimal = Decimal(0)
    ask: Decimal = Decimal(0)
    server_time_ms: int = 0
    recv_time_mono: float = 0.0
    is_newest: bool = True  # False for historical ticks within a batch
    pair: str | None = None
    broker_timestamp: datetime | None = None
    local_receipt_time: float | None = None
    batch_sequence: int = 0
    run_counter: int = 0
    validation_status: TickValidationStatus = TickValidationStatus.MALFORMED

    def __post_init__(self) -> None:
        if self.local_receipt_time is None:
            object.__setattr__(self, "local_receipt_time", self.recv_time_mono)
        if self.broker_timestamp is None and self.server_time_ms:
            from datetime import timezone
            object.__setattr__(self, "broker_timestamp", datetime.fromtimestamp(
                self.server_time_ms / 1000, tz=timezone.utc
            ))
        if self.pair is None:
            object.__setattr__(self, "pair", self.broker_symbol)


@dataclass(frozen=True, slots=True)
class TickBatch:
    pair: str
    sequence_number: int
    run_counter: int
    tick_count: int
    has_gap: bool = False
    is_run_boundary: bool = False

    def __post_init__(self) -> None:
        if (not self.pair or isinstance(self.sequence_number, bool) or not isinstance(self.sequence_number, int)
                or isinstance(self.run_counter, bool) or not isinstance(self.run_counter, int)
                or isinstance(self.tick_count, bool) or not isinstance(self.tick_count, int)
                or self.sequence_number < 0 or self.run_counter < 0 or self.tick_count <= 0):
            raise ValueError("TickBatch requires pair, non-negative sequence/run, and positive tick count")


class SpreadTrend(str, Enum):
    WIDENING = "WIDENING"
    NARROWING = "NARROWING"
    STABLE = "STABLE"


class TickActivityLevel(str, Enum):
    NORMAL = "NORMAL"
    LOW = "LOW"
    NONE = "NONE"


@dataclass(frozen=True, slots=True)
class SpreadSnapshot:
    pair: str
    spread_pips: Decimal
    bid: Decimal
    ask: Decimal
    timestamp: datetime

    def __post_init__(self) -> None:
        if not self.pair:
            raise ValueError("spread snapshot pair is required")
        if (not self.spread_pips.is_finite() or self.spread_pips < 0
                or not self.bid.is_finite() or not self.ask.is_finite()
                or self.bid <= 0 or self.ask < self.bid):
            raise ValueError("spread snapshot prices and spread are invalid")
        if self.timestamp.tzinfo is None:
            raise ValueError("spread snapshot timestamp must be timezone-aware")


@dataclass(frozen=True, slots=True)
class SymbolMapping:
    """Maps a broker-specific symbol name to a canonical pair."""
    canonical_pair: str  # e.g. "EURUSD"
    broker_symbol: str   # e.g. "EURUSD_"
    contract: ContractSpec
    confirmed_by_owner: bool = False


ContractSpecification = ContractSpec
