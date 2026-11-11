"""In-memory fake broker adapter for testing.

No MT5, no network, no Wine. Exercises the adapter interface and
canonical mapping logic with deterministic synthetic data.
"""
from __future__ import annotations

from decimal import Decimal

from .broker_adapter import BrokerAdapter
from .broker_types import AccountInfo, ConnectionStatus, ContractSpec, Tick


class FakeBrokerAdapter(BrokerAdapter):
    """Deterministic fake for unit/integration tests.

    Pre-loaded with a configurable set of symbols and contract specs.
    Tracks connect/disconnect calls for assertion.
    """

    def __init__(
        self,
        symbols: dict[str, ContractSpec] | None = None,
        account: AccountInfo | None = None,
        fail_connect: bool = False,
    ) -> None:
        self._symbols = symbols or {}
        self._account = account
        self._fail_connect = fail_connect
        self._connected = False
        self.connect_count = 0
        self.disconnect_count = 0
        self.health_check_count = 0

    @property
    def connected(self) -> bool:
        return self._connected

    def connect(self) -> ConnectionStatus:
        self.connect_count += 1
        if self._fail_connect:
            self._connected = False
            return ConnectionStatus.ERROR
        self._connected = True
        return ConnectionStatus.CONNECTED

    def disconnect(self) -> None:
        self.disconnect_count += 1
        self._connected = False

    def health_check(self) -> ConnectionStatus:
        self.health_check_count += 1
        if not self._connected:
            return ConnectionStatus.DISCONNECTED
        return ConnectionStatus.CONNECTED

    def get_account_info(self) -> AccountInfo | None:
        if not self._connected:
            return None
        return self._account

    def discover_symbols(self) -> list[str]:
        if not self._connected:
            return []
        return list(self._symbols.keys())

    def get_contract_spec(self, broker_symbol: str) -> ContractSpec | None:
        if not self._connected:
            return None
        return self._symbols.get(broker_symbol)


def make_contract(
    broker_symbol: str,
    digits: int = 5,
    point: str = "0.00001",
    tick_size: str = "0.00001",
    tick_value: str = "1.0",
    contract_size: str = "100000",
    volume_min: str = "0.01",
    volume_max: str = "100.0",
    volume_step: str = "0.01",
    min_stop_distance: str = "0",
    trade_allowed: bool = True,
) -> ContractSpec:
    """Convenience builder for test contract specs."""
    return ContractSpec(
        broker_symbol=broker_symbol,
        digits=digits,
        point=Decimal(point),
        tick_size=Decimal(tick_size),
        tick_value=Decimal(tick_value),
        contract_size=Decimal(contract_size),
        volume_min=Decimal(volume_min),
        volume_max=Decimal(volume_max),
        volume_step=Decimal(volume_step),
        min_stop_distance=Decimal(min_stop_distance),
        trade_allowed=trade_allowed,
        margin_initial=None,
        commission_per_lot=None,
        swap_long=None,
        swap_short=None,
    )


def make_tick(
    broker_symbol: str = "EURUSD",
    bid: str = "1.10000",
    ask: str = "1.10020",
    server_time_ms: int = 1_700_000_000_000,
    recv_time_mono: float = 0.0,
) -> Tick:
    """Convenience builder for test ticks."""
    return Tick(
        broker_symbol=broker_symbol,
        bid=Decimal(bid),
        ask=Decimal(ask),
        server_time_ms=server_time_ms,
        recv_time_mono=recv_time_mono,
    )


def make_demo_account() -> AccountInfo:
    """Standard demo account for tests."""
    return AccountInfo(
        login=12345678,
        server="MetaQuotes-Demo",
        currency="USD",
        balance=Decimal("10000.00"),
        equity=Decimal("10000.00"),
        margin_free=Decimal("10000.00"),
        account_type="demo",
        leverage=100,
        company="MetaQuotes Software Corp",
    )
