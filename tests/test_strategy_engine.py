"""Phase 4 strategy engine tests.

Covers: strategy types, market regime detection, all three strategies,
the orchestrator, and the safe-start (unconfigured = no signal) invariant.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from scalping_core.broker_types import ContractSpec, Tick
from scalping_core.strategy_types import (
    MarketRegime,
    PricePoint,
    Signal,
    SignalDirection,
    StrategyType,
)
from scalping_core.market_regime import RegimeConfig, RegimeDetector
from scalping_core.momentum_strategy import MomentumConfig, MomentumStrategy
from scalping_core.breakout_strategy import BreakoutConfig, BreakoutStrategy
from scalping_core.mean_reversion_strategy import MeanReversionConfig, MeanReversionStrategy
from scalping_core.strategy_engine import (
    DEFAULT_REGIME_MAP,
    PairStrategyConfig,
    PairStrategyEngine,
    StrategyEngine,
)

# Explicit regime map for tests that need routing.  Owner must supply this.
_TEST_REGIME_MAP = dict(DEFAULT_REGIME_MAP)

D = Decimal


def _point(mid: str, t_ms: int = 1000, mono: float = 1.0) -> PricePoint:
    m = D(mid)
    spread = D("0.00010")
    return PricePoint(
        mid=m, bid=m - spread / 2, ask=m + spread / 2,
        server_time_ms=t_ms, recv_time_mono=mono,
    )


def _tick(bid: str, ask: str, t_ms: int = 1000, mono: float = 1.0) -> Tick:
    return Tick(
        broker_symbol="EURUSD",
        bid=D(bid), ask=D(ask),
        server_time_ms=t_ms, recv_time_mono=mono,
    )


def _contract() -> ContractSpec:
    return ContractSpec(
        broker_symbol="EURUSD", digits=5, point=D("0.00001"),
        tick_size=D("0.00001"), tick_value=D("0.01"),
        contract_size=D("100000"), volume_min=D("0.01"),
        volume_max=D("100"), volume_step=D("0.01"),
        min_stop_distance=D("0.00050"), trade_allowed=True,
        margin_initial=None, commission_per_lot=None,
        swap_long=None, swap_short=None,
    )


# --- Safe start: unconfigured = no signal ---

class TestSafeStart:
    def test_regime_detector_returns_none_when_unconfigured(self):
        det = RegimeDetector()
        for i in range(200):
            result = det.update(_point("1.10000", t_ms=i * 100, mono=i * 0.1))
        assert result is None

    def test_momentum_returns_none_when_unconfigured(self):
        strat = MomentumStrategy()
        for i in range(100):
            strat.update(_point("1.10000", t_ms=i * 100, mono=i * 0.1))
        assert strat.generate_signal("EURUSD", MarketRegime.TRENDING) is None

    def test_breakout_returns_none_when_unconfigured(self):
        strat = BreakoutStrategy()
        for i in range(100):
            strat.update(_point("1.10000", t_ms=i * 100, mono=i * 0.1))
        assert strat.generate_signal("EURUSD", MarketRegime.BREAKOUT) is None

    def test_mean_reversion_returns_none_when_unconfigured(self):
        strat = MeanReversionStrategy()
        for i in range(100):
            strat.update(_point("1.10000", t_ms=i * 100, mono=i * 0.1))
        assert strat.generate_signal("EURUSD", MarketRegime.RANGING) is None

    def test_pair_engine_returns_none_when_unconfigured(self):
        engine = PairStrategyEngine("EURUSD")
        contract = _contract()
        for i in range(200):
            sig = engine.on_tick(
                _tick("1.09995", "1.10005", t_ms=i * 100, mono=i * 0.1),
                contract,
            )
        assert sig is None

    def test_strategy_engine_returns_none_for_unregistered_pair(self):
        engine = StrategyEngine()
        assert engine.on_tick("EURUSD", _tick("1.09995", "1.10005"), _contract()) is None


# --- Regime detection with configured thresholds ---

class TestRegimeDetector:
    def _trending_config(self) -> RegimeConfig:
        return RegimeConfig(
            window_size=30,
            trend_slope_threshold=D("0.00001"),
            high_volatility_threshold=D("0.00100"),
            low_volatility_threshold=D("0.00001"),
            range_width_ratio_max=D("0.0005"),
        )

    def test_trending_regime(self):
        det = RegimeDetector(self._trending_config())
        for i in range(30):
            price = D("1.10000") + D(str(i)) * D("0.00010")
            result = det.update(_point(str(price), t_ms=i * 100, mono=i * 0.1))
        assert result == MarketRegime.TRENDING

    def test_ranging_regime(self):
        cfg = RegimeConfig(
            window_size=30,
            trend_slope_threshold=D("0.01"),
            high_volatility_threshold=D("0.01"),
            low_volatility_threshold=D("0.0000001"),
            range_width_ratio_max=D("0.01"),
        )
        det = RegimeDetector(cfg)
        for i in range(30):
            price = D("1.10000") + (D("0.00001") if i % 2 == 0 else D("-0.00001"))
            result = det.update(_point(str(price), t_ms=i * 100, mono=i * 0.1))
        assert result == MarketRegime.RANGING

    def test_unstable_on_tick_gap(self):
        cfg = RegimeConfig(
            window_size=10,
            trend_slope_threshold=D("0.00001"),
            unstable_tick_gap_ms=5000,
        )
        det = RegimeDetector(cfg)
        for i in range(5):
            det.update(_point("1.10000", t_ms=i * 100, mono=i * 0.1))
        result = det.update(_point("1.10000", t_ms=100000, mono=100.0))
        assert result == MarketRegime.UNSTABLE


# --- Momentum strategy with configured thresholds ---

class TestMomentumStrategy:
    def _config(self) -> MomentumConfig:
        return MomentumConfig(
            window_size=30,
            ema_fast_span=5,
            ema_slow_span=10,
            min_ema_spread=D("0.00001"),
            min_velocity=D("0.0000001"),
            min_strength=D("0.1"),
        )

    def test_buy_signal_on_upward_momentum(self):
        strat = MomentumStrategy(self._config())
        for i in range(30):
            price = D("1.10000") + D(str(i)) * D("0.00010")
            strat.update(_point(str(price), t_ms=i * 1000, mono=float(i)))
        sig = strat.generate_signal("EURUSD", MarketRegime.TRENDING)
        assert sig is not None
        assert sig.direction == SignalDirection.BUY
        assert sig.strategy == StrategyType.MOMENTUM

    def test_sell_signal_on_downward_momentum(self):
        strat = MomentumStrategy(self._config())
        for i in range(30):
            price = D("1.10000") - D(str(i)) * D("0.00010")
            strat.update(_point(str(price), t_ms=i * 1000, mono=float(i)))
        sig = strat.generate_signal("EURUSD", MarketRegime.TRENDING)
        assert sig is not None
        assert sig.direction == SignalDirection.SELL


# --- Breakout strategy ---

class TestBreakoutStrategy:
    def _config(self) -> BreakoutConfig:
        return BreakoutConfig(
            window_size=40,
            lookback=20,
            min_breakout_distance=D("0.00020"),
            min_range_width=D("0.00005"),
            min_strength=D("0.1"),
        )

    def test_buy_breakout(self):
        strat = BreakoutStrategy(self._config())
        spread = D("0.00010")
        for i in range(30):
            mid = D("1.10000") + (D("0.00001") if i % 2 == 0 else D("-0.00001"))
            strat.update(PricePoint(
                mid=mid, bid=mid - spread / 2, ask=mid + spread / 2,
                server_time_ms=i * 100, recv_time_mono=i * 0.1,
            ))
        # Spike up
        spike = D("1.10050")
        strat.update(PricePoint(
            mid=spike, bid=spike - spread / 2, ask=spike + spread / 2,
            server_time_ms=3100, recv_time_mono=31.0,
        ))
        sig = strat.generate_signal("EURUSD", MarketRegime.BREAKOUT)
        assert sig is not None
        assert sig.direction == SignalDirection.BUY

    def test_no_signal_without_breakout(self):
        strat = BreakoutStrategy(self._config())
        for i in range(40):
            strat.update(_point("1.10000", t_ms=i * 100, mono=i * 0.1))
        assert strat.generate_signal("EURUSD", MarketRegime.BREAKOUT) is None


# --- Mean reversion strategy ---

class TestMeanReversionStrategy:
    def _config(self) -> MeanReversionConfig:
        return MeanReversionConfig(
            window_size=30,
            bb_period=20,
            entry_sigma=D("2.0"),
            min_strength=D("0.1"),
        )

    def test_buy_signal_on_oversold(self):
        strat = MeanReversionStrategy(self._config())
        for i in range(19):
            strat.update(_point("1.10000", t_ms=i * 100, mono=i * 0.1))
        # Price drops well below mean
        strat.update(_point("1.09900", t_ms=2000, mono=20.0))
        sig = strat.generate_signal("EURUSD", MarketRegime.RANGING)
        assert sig is not None
        assert sig.direction == SignalDirection.BUY

    def test_no_signal_at_mean(self):
        strat = MeanReversionStrategy(self._config())
        for i in range(30):
            strat.update(_point("1.10000", t_ms=i * 100, mono=i * 0.1))
        assert strat.generate_signal("EURUSD", MarketRegime.RANGING) is None


# --- Full orchestrator ---

class TestStrategyEngine:
    def test_register_and_route(self):
        engine = StrategyEngine()
        engine.register_pair("EURUSD")
        assert "EURUSD" in engine.pairs

    def test_remove_pair(self):
        engine = StrategyEngine()
        engine.register_pair("EURUSD")
        engine.remove_pair("EURUSD")
        assert "EURUSD" not in engine.pairs

    def test_no_signal_when_regime_map_absent(self):
        """Regime thresholds configured but no regime_map → no signal."""
        config = PairStrategyConfig(
            regime=RegimeConfig(
                window_size=30,
                trend_slope_threshold=D("0.00001"),
                high_volatility_threshold=D("0.01"),
                low_volatility_threshold=D("0.0000001"),
                range_width_ratio_max=D("0.001"),
            ),
            momentum=MomentumConfig(
                window_size=30,
                ema_fast_span=5,
                ema_slow_span=10,
                min_ema_spread=D("0.00001"),
                min_velocity=D("0.0000001"),
                min_strength=D("0.01"),
            ),
            # regime_map intentionally None — not owner-approved
        )
        engine = PairStrategyEngine("EURUSD", config)
        contract = _contract()
        sig = None
        for i in range(30):
            price = D("1.10000") + D(str(i)) * D("0.00010")
            spread = D("0.00010")
            sig = engine.on_tick(
                _tick(str(price - spread / 2), str(price + spread / 2),
                      t_ms=i * 1000, mono=float(i)),
                contract,
            )
        assert sig is None
        assert engine.last_regime is not None  # regime detected but routing blocked

    def test_configured_engine_produces_signal(self):
        """Full pipeline: regime → strategy → signal, with all thresholds AND regime_map set."""
        config = PairStrategyConfig(
            regime=RegimeConfig(
                window_size=30,
                trend_slope_threshold=D("0.00001"),
                high_volatility_threshold=D("0.01"),
                low_volatility_threshold=D("0.0000001"),
                range_width_ratio_max=D("0.001"),
            ),
            momentum=MomentumConfig(
                window_size=30,
                ema_fast_span=5,
                ema_slow_span=10,
                min_ema_spread=D("0.00001"),
                min_velocity=D("0.0000001"),
                min_strength=D("0.01"),
            ),
            regime_map=_TEST_REGIME_MAP,
        )
        engine = PairStrategyEngine("EURUSD", config)
        contract = _contract()
        sig = None
        for i in range(30):
            price = D("1.10000") + D(str(i)) * D("0.00010")
            spread = D("0.00010")
            sig = engine.on_tick(
                _tick(str(price - spread / 2), str(price + spread / 2),
                      t_ms=i * 1000, mono=float(i)),
                contract,
            )
        assert sig is not None
        assert sig.direction == SignalDirection.BUY
        assert sig.strategy == StrategyType.MOMENTUM
        assert sig.canonical_pair == "EURUSD"
        assert engine.last_regime == MarketRegime.TRENDING


# --- Signal dataclass ---

class TestSignal:
    def test_signal_is_frozen(self):
        sig = Signal(
            direction=SignalDirection.BUY, strategy=StrategyType.MOMENTUM,
            regime=MarketRegime.TRENDING, strength=D("0.5"),
            canonical_pair="EURUSD", reference_price=D("1.10000"),
            timestamp_ms=1000,
        )
        with pytest.raises(AttributeError):
            sig.direction = SignalDirection.SELL  # type: ignore[misc]


class TestDefaultRegimeMap:
    def test_all_regimes_mapped(self):
        for regime in MarketRegime:
            assert regime in DEFAULT_REGIME_MAP
