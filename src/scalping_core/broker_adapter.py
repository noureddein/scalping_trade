"""Broker adapter interface and canonical symbol mapping.

Defines the abstract adapter boundary (§5) and the
``discover_canonical_mappings`` function for symbol discovery.

Architecture C (decisions #4–#8) uses a TCP adapter where the MQL5 EA
sends market/account data to the Python backend over 127.0.0.1. The
concrete TCP adapter is in ``tcp_broker_adapter.py``. Phase 2 scope is
read-only: connection health, account discovery, symbol discovery, and
contract specs. No order submission, modification, or cancellation.
"""
from __future__ import annotations

import abc
import re
from decimal import Decimal

from .broker_types import (
    AccountInfo,
    BrokerSymbol,
    ConnectionStatus,
    ContractSpec,
    SymbolMapping,
)
from .risk_gate import FOREX_CURRENCIES, _CANONICAL_PAIR, _NON_FOREX_BASES


class BrokerUnavailableError(RuntimeError):
    """Raised when broker data is not fresh and connected for this session."""


class SymbolUnavailableError(LookupError):
    """Raised when a broker symbol was not discovered or has no valid contract."""


class BrokerAdapter(abc.ABC):
    """Abstract read-only broker adapter (§5).

    Phase 2 covers connection, health, account, symbols, and contracts.
    Order-related methods are deliberately absent — they belong to a
    future phase and require separate owner approval.
    """

    @abc.abstractmethod
    def connect(self) -> ConnectionStatus:
        """Establish connection to the broker. Must not submit orders."""

    @abc.abstractmethod
    def disconnect(self) -> None:
        """Release connection resources."""

    @abc.abstractmethod
    def health_check(self) -> ConnectionStatus:
        """Non-mutating connectivity probe."""

    def get_connection_state(self) -> ConnectionStatus:
        """Return the current connection state, including reconnecting."""
        return self.health_check()

    @abc.abstractmethod
    def get_account_info(self) -> AccountInfo | None:
        """Return account details or None if unavailable."""

    @abc.abstractmethod
    def discover_symbols(self) -> list[BrokerSymbol]:
        """Return discovered broker symbols with their trading permissions."""

    @abc.abstractmethod
    def get_contract_spec(self, broker_symbol: str) -> ContractSpec | None:
        """Return a fresh spec or raise SymbolUnavailableError/BrokerUnavailableError."""

    def update_mapping(self, canonical_name: str, broker_name: str) -> SymbolMapping:
        """Owner-confirm a mapping for a currently discovered broker symbol."""
        raise NotImplementedError

    def get_mapping(self, canonical_name: str) -> SymbolMapping | None:
        """Return an owner-confirmed in-memory mapping, if one exists."""
        raise NotImplementedError


def _is_forex_canonical(pair: str) -> bool:
    if not _CANONICAL_PAIR.fullmatch(pair):
        return False
    base, quote = pair[:3], pair[3:]
    if base in _NON_FOREX_BASES or quote in _NON_FOREX_BASES:
        return False
    if base == quote:
        return False
    if base not in FOREX_CURRENCIES or quote not in FOREX_CURRENCIES:
        return False
    return True


def discover_canonical_mappings(
    adapter: BrokerAdapter,
    alias_overrides: dict[str, str] | None = None,
) -> list[SymbolMapping]:
    """Discover forex symbols and map them to canonical pairs.

    For each broker symbol, attempts to derive the canonical pair by
    stripping common suffixes (e.g. "EURUSD_" → "EURUSD", "EURUSDm" →
    "EURUSD"). Manual overrides in *alias_overrides* take precedence
    (keyed by broker_symbol → canonical_pair).

    Returns only valid forex pairs (6 uppercase letters, no gold/
    commodities, no self-pairs). Non-forex instruments are silently
    skipped.
    """
    overrides = alias_overrides or {}
    symbols = adapter.discover_symbols()
    mappings: list[SymbolMapping] = []

    for symbol in symbols:
        broker_sym = symbol.broker_name
        canonical = overrides.get(broker_sym)
        if canonical is None:
            canonical = _infer_canonical(broker_sym)
        if canonical is None or not _is_forex_canonical(canonical):
            continue

        try:
            spec = adapter.get_contract_spec(broker_sym)
        except SymbolUnavailableError:
            continue
        if spec is None:
            continue

        mappings.append(SymbolMapping(
            canonical_pair=canonical,
            broker_symbol=broker_sym,
            contract=spec,
        ))

    return mappings


_SUFFIX_PATTERN = re.compile(r"^([A-Z]{6})[._\-a-z]*$")


def _infer_canonical(broker_symbol: str) -> str | None:
    """Best-effort strip of broker suffixes to derive a canonical pair.

    Returns None if the symbol doesn't look like a 6-letter forex pair
    with an optional suffix.
    """
    m = _SUFFIX_PATTERN.match(broker_symbol)
    if m:
        return m.group(1)
    upper = broker_symbol.upper()
    if len(upper) >= 6 and _CANONICAL_PAIR.fullmatch(upper[:6]):
        return upper[:6]
    return None
