# Tick Protocol Contract

**Date**: 2026-11-10

**Extends**: Phase 2 TCP protocol (`specs/003-broker-connectivity/contracts/tcp-protocol.md`)

This contract defines the tick-related messages added to the existing
length-prefixed JSON TCP protocol between the MQL5 EA and the Python
backend.

## EA → Backend Messages

### TICK_DATA

Sent by the EA when new ticks are available. May contain one or more
ticks in a single message (batching).

```json
{
  "type": "TICK_DATA",
  "pair": "EURUSD",
  "run_counter": 1,
  "batch_sequence": 42,
  "dropped_count": 0,
  "ticks": [
    {
      "bid": 1.08542,
      "ask": 1.08557,
      "broker_timestamp": "2026-11-10T14:30:01.123Z"
    },
    {
      "bid": 1.08543,
      "ask": 1.08558,
      "broker_timestamp": "2026-11-10T14:30:01.456Z"
    }
  ]
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| type | string | Yes | Always `"TICK_DATA"` |
| pair | string | Yes | Broker symbol name (mapped to canonical via Phase 2) |
| run_counter | integer | Yes | EA run identifier; increments on EA restart |
| batch_sequence | integer | Yes | Monotonically increasing per run_counter |
| dropped_count | integer | No | EA ring-buffer overwrites known for this batch; defaults to 0 |
| ticks | array | Yes | One or more tick objects |
| ticks[].bid | decimal | Yes | Bid price; positive, finite |
| ticks[].ask | decimal | Yes | Ask price; positive, finite, >= bid |
| ticks[].broker_timestamp | string | Yes | ISO 8601 UTC; must advance within pair |

**Validation rules** (applied by the backend on receipt):

1. `pair` must map to a known canonical symbol (Phase 2 mapping).
2. Each tick: `bid > 0`, `ask > 0`, `ask >= bid`, both finite.
3. `broker_timestamp` must advance relative to the last accepted tick
   for this pair. Equal or earlier timestamps → reject as
   DUPLICATE/REORDERED.
4. `batch_sequence` must be >= last seen for the same `run_counter`.
   A gap marks the interval as degraded. A new `run_counter` resets
   sequence tracking.
5. Local receipt time is recorded by the backend (not sent by EA).
6. A positive `dropped_count` marks this batch interval degraded even
   when the batch sequence itself is contiguous.

**Rejection**: Invalid ticks are rejected individually within a batch.
Valid ticks in the same batch are still processed. The backend does NOT
send an error response for rejected ticks (fire-and-forget from EA
perspective). Rejected ticks are logged with a structured reason.

### MARKET_STATUS

Optional heartbeat-style message indicating the EA's view of market
state. Supplements tick-based detection on the backend.

```json
{
  "type": "MARKET_STATUS",
  "pair": "EURUSD",
  "is_market_open": true,
  "server_time": "2026-11-10T14:30:00.000Z"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| type | string | Yes | Always `"MARKET_STATUS"` |
| pair | string | Yes | Broker symbol name |
| is_market_open | boolean | Yes | EA's view of market open/closed |
| server_time | string | Yes | Broker server time, ISO 8601 UTC |

## Backend → EA Messages

No new backend-to-EA messages are introduced in Phase 3. Tick
delivery is EA-initiated. The backend passively receives and validates.

## Error Handling

- Malformed JSON: Drop the entire message, log parse error.
- Unknown `type`: Ignore (forward compatibility).
- Unknown `pair`: Reject all ticks in batch, log unknown symbol.
- Empty `ticks` array: Ignore message (no-op).

## Compatibility

- This contract adds message types to the Phase 2 protocol. It does
  not modify existing message types (HEARTBEAT, ACCOUNT_INFO, etc.).
- The EA and backend must both support TICK_DATA for Phase 3 to
  function. MARKET_STATUS is optional and supplementary.
