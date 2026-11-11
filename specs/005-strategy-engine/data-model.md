# Data Model: Phase 4 — Strategy Engine

**Date**: 2026-11-10

## Entities

### RegimeClassification

The current market regime for a pair at a point in time.

| Field | Type | Constraints |
|-------|------|-------------|
| pair | string | FK to CanonicalSymbol (Phase 2) |
| regime | enum | TRENDING, RANGING, BREAKOUT, HIGH_VOLATILITY, LOW_VOLATILITY, UNSTABLE, UNKNOWN |
| confidence_features | dict | Feature values used for classification |
| timestamp | datetime | Decision time; from tick's broker_timestamp |
| is_valid | boolean | False if insufficient history or degraded data |

**Classification priority** (highest wins):
1. UNSTABLE — degraded data, stale feed, gapped, insufficient history
2. HIGH_VOLATILITY — dispersion exceeds approved baseline
3. BREAKOUT — price outside prior range by approved margin
4. TRENDING — directional slope with EMA alignment
5. RANGING / LOW_VOLATILITY — narrow range, near-zero slope
6. UNKNOWN — none of the above or ambiguous

### RegimeMap

Explicit mapping from regime to strategy. Absent by default.

| Field | Type | Constraints |
|-------|------|-------------|
| mappings | dict | regime → strategy name; absent = no mapping |
| is_configured | boolean | False by default; True only when owner sets it |

**Validation**: A missing map or a regime not present in the map
produces no signal. UNSTABLE always produces no signal regardless
of mapping.

### StrategyConfig

Per-strategy parameter set. All fields absent by default.

| Field | Type | Constraints |
|-------|------|-------------|
| strategy_name | string | "momentum", "breakout", or "meanrev" |
| is_active | boolean | True only when all required params are set |
| parameters | dict | Strategy-specific; all must be finite, valid |

**Momentum parameters** (all required for activation):
- fast_ema_period, slow_ema_period: positive integers
- min_ema_spread: positive decimal (normalized units)
- min_velocity: positive decimal
- signal_quality_threshold: positive decimal

**Breakout parameters** (all required for activation):
- channel_lookback: positive integer (observations)
- min_channel_width: positive decimal (normalized units)
- breakout_margin: positive decimal (normalized units)
- signal_quality_threshold: positive decimal

**Mean reversion parameters** (all required for activation):
- rolling_period: positive integer (observations)
- deviation_threshold: positive decimal (standardized units)
- signal_quality_threshold: positive decimal

### FeatureSnapshot

Indicator values at a specific decision point.

| Field | Type | Constraints |
|-------|------|-------------|
| pair | string | FK to CanonicalSymbol |
| timestamp | datetime | Decision time |
| mid_price | decimal | (Bid + Ask) / 2; for indicators only |
| bid | decimal | Current Bid |
| ask | decimal | Current Ask |
| fast_ema | decimal or null | If momentum active |
| slow_ema | decimal or null | If momentum active |
| ema_spread | decimal or null | fast - slow |
| price_velocity | decimal or null | Rate of mid-price change |
| channel_high | decimal or null | If breakout active; Ask-side |
| channel_low | decimal or null | If breakout active; Bid-side |
| channel_width | decimal or null | high - low |
| rolling_mean | decimal or null | If meanrev active |
| rolling_std | decimal or null | If meanrev active |
| z_score | decimal or null | (price - mean) / std |
| volatility | decimal or null | Rolling dispersion |

### SignalRecommendation

A validated strategy output ready for downstream consumption.

| Field | Type | Constraints |
|-------|------|-------------|
| pair | string | FK to CanonicalSymbol |
| direction | enum | BUY or SELL |
| strategy_name | string | Which strategy produced it |
| regime | enum | Active regime at decision time |
| reference_bid | decimal | Bid at decision time |
| reference_ask | decimal | Ask at decision time |
| features | FeatureSnapshot | Full indicator state |
| strength | decimal | Strategy-local; not cross-comparable |
| timestamp | datetime | Decision time |
| signal_id | string | Unique identifier for tracking |

**Note**: This is a recommendation, not an order. Downstream execution
must obtain a fresh quote and rerun all spread/risk/account checks.

### NoSignalReason

Structured explanation for why no signal was produced.

| Field | Type | Constraints |
|-------|------|-------------|
| pair | string | FK to CanonicalSymbol |
| reason_code | enum | See reason codes below |
| detail | string | Human-readable context |
| timestamp | datetime | When evaluated |

**Reason codes**: INSUFFICIENT_HISTORY, DEGRADED_DATA, UNSTABLE_REGIME,
NO_REGIME_MAP, REGIME_NOT_MAPPED, STRATEGY_INACTIVE, MISSING_PARAMS,
INVALID_CONFIG, BELOW_QUALITY_THRESHOLD, NO_SIGNAL_CONDITIONS,
PROHIBITED_REGIME, ZERO_VARIANCE, SPREAD_ONLY_BREAKOUT,
CHANNEL_TOO_NARROW.

## Relationships

```
CanonicalSymbol (Phase 2) 1──1 RegimeClassification (current)
RegimeMap 1──* regime-to-strategy mappings
StrategyConfig 1──1 per strategy name
SignalRecommendation *──1 CanonicalSymbol
SignalRecommendation 1──1 FeatureSnapshot
```

## Notes

- All entities are in-memory for Phase 4. No database persistence.
- FeatureSnapshot is attached to every SignalRecommendation for
  diagnostics and future replay verification.
- NoSignalReason is logged for every evaluation that does not produce
  a signal, enabling test assertions and operational diagnostics.
