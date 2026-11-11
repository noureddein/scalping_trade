"""Tests for broker adapter interface, fake adapter, and canonical mapping.

No MT5, no network, no Wine. Exercises the adapter contract and
symbol-discovery logic with deterministic synthetic data.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from scalping_core.broker_adapter import (
    BrokerAdapter,
    BrokerUnavailableError,
    SymbolUnavailableError,
    _infer_canonical,
    _is_forex_canonical,
    discover_canonical_mappings,
)
from scalping_core.broker_types import (
    AccountInfo,
    ConnectionStatus,
    ContractSpec,
    SymbolMapping,
)
from scalping_core.fake_broker import (
    FakeBrokerAdapter,
    make_contract,
    make_demo_account,
)


# ---------------------------------------------------------------------------
# Canonical pair validation
# ---------------------------------------------------------------------------


class TestIsForexCanonical:
    def test_valid_pairs(self):
        for pair in ("EURUSD", "GBPJPY", "AUDUSD", "NZDJPY", "USDCHF", "EURGBP"):
            assert _is_forex_canonical(pair) is True, f"{pair} should be valid"

    def test_rejects_gold(self):
        assert _is_forex_canonical("XAUUSD") is False

    def test_rejects_silver(self):
        assert _is_forex_canonical("XAGUSD") is False

    def test_rejects_self_pair(self):
        assert _is_forex_canonical("USDUSD") is False

    def test_rejects_short(self):
        assert _is_forex_canonical("EUR") is False

    def test_rejects_lowercase(self):
        assert _is_forex_canonical("eurusd") is False

    def test_rejects_seven_chars(self):
        assert _is_forex_canonical("EURUSDD") is False

    def test_rejects_crypto_btcusd(self):
        assert _is_forex_canonical("BTCUSD") is False

    def test_rejects_crypto_ethusd(self):
        assert _is_forex_canonical("ETHUSD") is False

    def test_rejects_crypto_ltcusd(self):
        assert _is_forex_canonical("LTCUSD") is False

    def test_rejects_crypto_xrpusd(self):
        assert _is_forex_canonical("XRPUSD") is False

    def test_rejects_unknown_currency(self):
        assert _is_forex_canonical("ABCUSD") is False

    def test_rejects_unknown_quote(self):
        assert _is_forex_canonical("EURXYZ") is False

    def test_accepts_iso_currencies(self):
        """Representative ISO 4217 currencies from the supported set."""
        for pair in ("USDTHB", "USDINR", "USDKRW", "USDBRL",
                     "USDRUB", "USDSAR", "USDTWD", "USDPHP", "USDIDR",
                     "USDMYR", "USDCLP", "USDCOP", "USDPEN", "USDKWD",
                     "USDCNY"):
            assert _is_forex_canonical(pair) is True, f"{pair} should be valid"

    def test_accepts_cnh_broker_convention(self):
        """CNH is not ISO 4217 but is a standard broker convention for
        offshore yuan. It is in _BROKER_CONVENTION_CURRENCIES."""
        assert _is_forex_canonical("USDCNH") is True
        assert _is_forex_canonical("CNHJPY") is True

    def test_rejects_unsupported_fiat(self):
        """Fiat currencies not in the supported set are rejected.
        This is a curated subset, not the full ISO 4217 universe."""
        assert _is_forex_canonical("USDXOF") is False  # West African CFA franc
        assert _is_forex_canonical("USDKHR") is False  # Cambodian riel
        assert _is_forex_canonical("USDMMK") is False  # Myanmar kyat


# ---------------------------------------------------------------------------
# Infer canonical from broker symbol
# ---------------------------------------------------------------------------


class TestInferCanonical:
    def test_exact_six(self):
        assert _infer_canonical("EURUSD") == "EURUSD"

    def test_underscore_suffix(self):
        assert _infer_canonical("EURUSD_") == "EURUSD"

    def test_dot_suffix(self):
        assert _infer_canonical("EURUSD.raw") == "EURUSD"

    def test_lowercase_suffix(self):
        assert _infer_canonical("EURUSDm") == "EURUSD"

    def test_mixed_suffix(self):
        assert _infer_canonical("GBPJPY_ecn") == "GBPJPY"

    def test_too_short(self):
        assert _infer_canonical("EUR") is None

    def test_numeric_only(self):
        assert _infer_canonical("123456") is None

    def test_non_alpha_start(self):
        assert _infer_canonical("#EURUSD") is None


# ---------------------------------------------------------------------------
# FakeBrokerAdapter
# ---------------------------------------------------------------------------


class TestFakeAdapterConnect:
    def test_connect_success(self):
        adapter = FakeBrokerAdapter()
        status = adapter.connect()
        assert status is ConnectionStatus.CONNECTED
        assert adapter.connected is True
        assert adapter.connect_count == 1

    def test_connect_failure(self):
        adapter = FakeBrokerAdapter(fail_connect=True)
        status = adapter.connect()
        assert status is ConnectionStatus.ERROR
        assert adapter.connected is False

    def test_disconnect(self):
        adapter = FakeBrokerAdapter()
        adapter.connect()
        adapter.disconnect()
        assert adapter.connected is False
        assert adapter.disconnect_count == 1

    def test_health_check_connected(self):
        adapter = FakeBrokerAdapter()
        adapter.connect()
        assert adapter.health_check() is ConnectionStatus.CONNECTED

    def test_health_check_disconnected(self):
        adapter = FakeBrokerAdapter()
        assert adapter.health_check() is ConnectionStatus.DISCONNECTED


class TestFakeAdapterAccount:
    def test_account_when_connected(self):
        acct = make_demo_account()
        adapter = FakeBrokerAdapter(account=acct)
        adapter.connect()
        info = adapter.get_account_info()
        assert info is not None
        assert info.login == 12345678
        assert info.currency == "USD"
        assert info.account_type == "demo"

    def test_account_when_disconnected(self):
        acct = make_demo_account()
        adapter = FakeBrokerAdapter(account=acct)
        with pytest.raises(BrokerUnavailableError):
            adapter.get_account_info()


class TestFakeAdapterSymbols:
    def test_discover_symbols_connected(self):
        specs = {"EURUSD_": make_contract("EURUSD_"), "GBPJPY": make_contract("GBPJPY")}
        adapter = FakeBrokerAdapter(symbols=specs)
        adapter.connect()
        syms = adapter.discover_symbols()
        assert {symbol.broker_name for symbol in syms} == {"EURUSD_", "GBPJPY"}
        assert all(symbol.trading_permitted for symbol in syms)

    def test_discover_symbols_disconnected(self):
        specs = {"EURUSD_": make_contract("EURUSD_")}
        adapter = FakeBrokerAdapter(symbols=specs)
        with pytest.raises(BrokerUnavailableError):
            adapter.discover_symbols()

    def test_get_contract_spec(self):
        spec = make_contract("EURUSD_", digits=5, point="0.00001")
        adapter = FakeBrokerAdapter(symbols={"EURUSD_": spec})
        adapter.connect()
        result = adapter.get_contract_spec("EURUSD_")
        assert result is not None
        assert result.digits == 5
        assert result.point == Decimal("0.00001")

    def test_get_contract_spec_unknown(self):
        adapter = FakeBrokerAdapter(symbols={"EURUSD_": make_contract("EURUSD_")})
        adapter.connect()
        with pytest.raises(SymbolUnavailableError, match="symbol unavailable"):
            adapter.get_contract_spec("XYZABC")


# ---------------------------------------------------------------------------
# discover_canonical_mappings
# ---------------------------------------------------------------------------


class TestDiscoverCanonicalMappings:
    def _adapter_with_symbols(self, *broker_symbols: str) -> FakeBrokerAdapter:
        specs = {s: make_contract(s) for s in broker_symbols}
        adapter = FakeBrokerAdapter(symbols=specs)
        adapter.connect()
        return adapter

    def test_basic_mapping(self):
        adapter = self._adapter_with_symbols("EURUSD_", "GBPJPY")
        mappings = discover_canonical_mappings(adapter)
        canonical_pairs = {m.canonical_pair for m in mappings}
        assert canonical_pairs == {"EURUSD", "GBPJPY"}

    def test_skips_gold(self):
        adapter = self._adapter_with_symbols("XAUUSD", "EURUSD")
        mappings = discover_canonical_mappings(adapter)
        assert len(mappings) == 1
        assert mappings[0].canonical_pair == "EURUSD"

    def test_skips_unrecognized(self):
        adapter = self._adapter_with_symbols("SP500", "EURUSD")
        mappings = discover_canonical_mappings(adapter)
        assert len(mappings) == 1

    def test_alias_override(self):
        adapter = self._adapter_with_symbols("EU_special")
        mappings = discover_canonical_mappings(
            adapter, alias_overrides={"EU_special": "EURUSD"}
        )
        assert len(mappings) == 1
        assert mappings[0].canonical_pair == "EURUSD"
        assert mappings[0].broker_symbol == "EU_special"

    def test_alias_override_rejects_invalid_canonical(self):
        adapter = self._adapter_with_symbols("GOLD")
        mappings = discover_canonical_mappings(
            adapter, alias_overrides={"GOLD": "XAUUSD"}
        )
        assert len(mappings) == 0

    def test_skips_crypto_btcusd(self):
        adapter = self._adapter_with_symbols("BTCUSD", "EURUSD")
        mappings = discover_canonical_mappings(adapter)
        assert len(mappings) == 1
        assert mappings[0].canonical_pair == "EURUSD"

    def test_skips_crypto_ethusd(self):
        adapter = self._adapter_with_symbols("ETHUSD")
        mappings = discover_canonical_mappings(adapter)
        assert len(mappings) == 0

    def test_alias_override_rejects_crypto(self):
        adapter = self._adapter_with_symbols("BTC_special")
        mappings = discover_canonical_mappings(
            adapter, alias_overrides={"BTC_special": "BTCUSD"}
        )
        assert len(mappings) == 0

    def test_alias_override_rejects_unknown_currency(self):
        adapter = self._adapter_with_symbols("WEIRD")
        mappings = discover_canonical_mappings(
            adapter, alias_overrides={"WEIRD": "ABCUSD"}
        )
        assert len(mappings) == 0

    def test_disconnected_returns_empty(self):
        adapter = FakeBrokerAdapter(symbols={"EURUSD": make_contract("EURUSD")})
        # not connected
        with pytest.raises(BrokerUnavailableError):
            discover_canonical_mappings(adapter)

    def test_mapping_carries_contract(self):
        spec = make_contract("USDJPY", digits=3, point="0.001")
        adapter = FakeBrokerAdapter(symbols={"USDJPY": spec})
        adapter.connect()
        mappings = discover_canonical_mappings(adapter)
        assert len(mappings) == 1
        assert mappings[0].contract.digits == 3
        assert mappings[0].contract.point == Decimal("0.001")

    def test_multiple_suffixed_symbols(self):
        adapter = self._adapter_with_symbols(
            "EURUSD_", "EURUSD.raw", "GBPUSD_", "USDJPY"
        )
        mappings = discover_canonical_mappings(adapter)
        canonical_pairs = [m.canonical_pair for m in mappings]
        assert "EURUSD" in canonical_pairs
        assert "GBPUSD" in canonical_pairs
        assert "USDJPY" in canonical_pairs


# ---------------------------------------------------------------------------
# ContractSpec and AccountInfo value types
# ---------------------------------------------------------------------------


class TestContractSpec:
    def test_frozen(self):
        spec = make_contract("EURUSD")
        with pytest.raises(AttributeError):
            spec.digits = 3  # type: ignore[misc]

    def test_all_fields_present(self):
        spec = make_contract("EURUSD")
        assert spec.broker_symbol == "EURUSD"
        assert spec.volume_min == Decimal("0.01")
        assert spec.trade_allowed is True
        assert spec.margin_initial == Decimal("1000")


class TestAccountInfo:
    def test_frozen(self):
        acct = make_demo_account()
        with pytest.raises(AttributeError):
            acct.login = 0  # type: ignore[misc]

    def test_fields(self):
        acct = make_demo_account()
        assert acct.server == "MetaQuotes-Demo"
        assert acct.leverage == 100


# ---------------------------------------------------------------------------
# BrokerAdapter is abstract
# ---------------------------------------------------------------------------


class TestBrokerAdapterAbstract:
    def test_cannot_instantiate(self):
        with pytest.raises(TypeError):
            BrokerAdapter()  # type: ignore[abstract]
