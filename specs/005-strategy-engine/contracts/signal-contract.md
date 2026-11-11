# Signal Recommendation Contract

**Date**: 2026-11-10

**Scope**: Defines the interface between the strategy engine (Phase 4)
and downstream execution/risk (Phase 5). The strategy engine produces
SignalRecommendations; execution consumes them.

## Signal Recommendation Payload

When a strategy produces a valid, quality-checked signal, the
recommendation contains:

```json
{
  "signal_id": "uuid-v5",
  "pair": "EURUSD",
  "direction": "BUY",
  "strategy_name": "momentum",
  "regime": "TRENDING",
  "reference_bid": 1.08542,
  "reference_ask": 1.08557,
  "strength": 0.73,
  "features": {
    "mid_price": 1.085495,
    "fast_ema": 1.08548,
    "slow_ema": 1.08530,
    "ema_spread": 0.00018,
    "price_velocity": 0.00003,
    "volatility": 0.00012
  },
  "timestamp": "2026-11-10T14:30:01.123Z"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| signal_id | string | Yes | Deterministic UUID v5 for tracking/correlation; identical recommendation inputs produce the same ID |
| pair | string | Yes | Canonical symbol name |
| direction | enum | Yes | BUY or SELL |
| strategy_name | string | Yes | "momentum", "breakout", or "meanrev" |
| regime | enum | Yes | Active regime at decision time |
| reference_bid | decimal | Yes | Bid at decision time (informational) |
| reference_ask | decimal | Yes | Ask at decision time (informational) |
| strength | decimal | Yes | Strategy-local signal strength; NOT cross-comparable |
| features | object | Yes | Full FeatureSnapshot at decision time |
| timestamp | string | Yes | ISO 8601 UTC; decision time |

## No-Signal Response

When evaluation produces no signal, a structured reason is logged:

```json
{
  "pair": "EURUSD",
  "reason_code": "STRATEGY_INACTIVE",
  "detail": "Momentum strategy has no configured parameters",
  "timestamp": "2026-11-10T14:30:01.123Z"
}
```

## Consumer Obligations

1. **Fresh quote**: Downstream MUST obtain a fresh Bid/Ask quote
   before any execution decision. The recommendation's reference
   prices are informational snapshots, not executable prices.
2. **Independent gates**: Downstream MUST independently verify spread,
   risk, account, reservation, margin, and broker connectivity.
3. **No stale signals**: If the signal's timestamp exceeds a
   configurable staleness threshold relative to the current time,
   downstream MUST discard it.
4. **strength is not comparable**: Downstream MUST NOT compare
   strength values across different strategy names.

## Producer Guarantees

1. Every SignalRecommendation passes quality validation before emission.
2. The features snapshot reflects the exact indicator state at decision
   time — no look-ahead.
3. Identical input and configuration produce identical signals,
   including the deterministic UUID v5 identifier.
4. The strategy engine never calls order APIs, modifies positions, or
   changes account state.
5. With no parameters configured, zero signals are produced.
