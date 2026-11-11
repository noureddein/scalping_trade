"""Shared types for the strategy engine (§7, §8 steps 1–13).

Pure data. No I/O, no execution, no order submission.
All threshold/parameter fields are owner decisions (§19) and default to None
(inactive). No signals are generated until the owner configures values.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


class SignalDirection(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    NO_TRADE = "NO_TRADE"


class StrategyType(str, Enum):
    MOMENTUM = "MOMENTUM"
    BREAKOUT = "BREAKOUT"
    MEAN_REVERSION = "MEAN_REVERSION"


class MarketRegime(str, Enum):
    TRENDING = "TRENDING"
    RANGING = "RANGING"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    LOW_VOLATILITY = "LOW_VOLATILITY"
    BREAKOUT = "BREAKOUT"
    UNSTABLE = "UNSTABLE"


@dataclass(frozen=True, slots=True)
class Signal:
    """A strategy's output. Read-only recommendation — never triggers execution.

    reference_price is the bid/ask at signal time, for logging only.
    Phase 5 execution must obtain and validate a fresh quote independently.
    """
    direction: SignalDirection
    strategy: StrategyType
    regime: MarketRegime
    strength: Decimal
    canonical_pair: str
    reference_price: Decimal
    timestamp_ms: int


@dataclass(frozen=True, slots=True)
class PricePoint:
    """Price snapshot derived from a validated tick for strategy consumption.

    Price basis:
      - mid: arithmetic midpoint (bid + ask) / 2, used for indicator
        calculations (EMA, Bollinger, regime detection).  NOT a tradeable
        price — strategies use bid (for SELL) or ask (for BUY) as
        reference_price on the Signal they emit (logging only).
      - bid/ask: preserved from the source Tick for entry price selection.

    Timestamp semantics:
      - server_time_ms: broker server time in milliseconds since Unix epoch,
        as reported by the EA.  Used for inter-tick timing (velocity, gaps).
      - recv_time_mono: Python-side monotonic clock at tick receipt.  Used
        only for local staleness checks in PairFeed, not by strategies.

    Stale input:
      The strategy engine does NOT re-validate staleness.  Ticks must pass
      through PairFeed.process_tick() (market_data.py) before reaching the
      strategy engine.  PairFeed rejects duplicates, out-of-order ticks,
      and invalid bid/ask.  Feed freshness is checked by PairFeed.is_fresh()
      and enforced by the risk gate (EntryCheck.market_data_fresh).
    """
    mid: Decimal
    bid: Decimal
    ask: Decimal
    server_time_ms: int
    recv_time_mono: float
