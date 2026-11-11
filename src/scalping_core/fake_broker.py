"""In-memory fake broker adapter for testing.

No MT5, no network, no Wine. Exercises the adapter interface and
canonical mapping logic with deterministic synthetic data.
"""
from __future__ import annotations

from decimal import Decimal

from .broker_adapter import BrokerAdapter, BrokerUnavailableError, SymbolUnavailableError, _is_forex_canonical
from .broker_types import AccountInfo, BrokerSymbol, ConnectionStatus, ContractSpec, SymbolMapping, Tick


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
        self._owner_mappings: dict[str, SymbolMapping] = {}
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
            raise BrokerUnavailableError("broker unavailable")
        return self._account

    def discover_symbols(self) -> list[BrokerSymbol]:
        if not self._connected:
            raise BrokerUnavailableError("broker unavailable")
        account_number = self._account.login if self._account else None
        return [
            BrokerSymbol(name, spec.trade_allowed, account_number)
            for name, spec in self._symbols.items()
        ]

    def get_contract_spec(self, broker_symbol: str) -> ContractSpec | None:
        if not self._connected:
            raise BrokerUnavailableError("broker unavailable")
        spec = self._symbols.get(broker_symbol)
        if spec is None:
            raise SymbolUnavailableError(f"symbol unavailable: {broker_symbol}")
        return spec

    def update_mapping(self, canonical_name: str, broker_name: str) -> SymbolMapping:
        if not self._connected:
            raise BrokerUnavailableError("broker unavailable")
        if not _is_forex_canonical(canonical_name):
            raise ValueError(f"invalid canonical Forex symbol: {canonical_name}")
        symbol = next(
            (item for item in self.discover_symbols() if item.broker_name == broker_name),
            None,
        )
        if symbol is None:
            raise ValueError(f"broker symbol unavailable: {broker_name}")
        contract = self.get_contract_spec(broker_name)
        if any(
            item.broker_symbol == broker_name and key != canonical_name
            for key, item in self._owner_mappings.items()
        ):
            raise ValueError(f"broker symbol already mapped: {broker_name}")
        mapping = SymbolMapping(canonical_name, broker_name, contract, True)
        self._owner_mappings[canonical_name] = mapping
        return mapping

    def get_mapping(self, canonical_name: str) -> SymbolMapping | None:
        return self._owner_mappings.get(canonical_name)


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
        margin_initial=Decimal("1000"),
        commission_per_lot=Decimal("0"),
        swap_long=Decimal("0"),
        swap_short=Decimal("0"),
        trading_permissions="FULL" if trade_allowed else "DISABLED",
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
