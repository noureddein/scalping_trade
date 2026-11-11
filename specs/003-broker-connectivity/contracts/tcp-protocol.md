# TCP Protocol Contract: EA ↔ Backend

**Date**: 2026-11-10

## Transport

- TCP over loopback 127.0.0.1
- One connection per EA instance
- Length-prefixed JSON messages (4-byte big-endian length header
  followed by UTF-8 JSON payload)

## Message Types (EA → Backend)

### HEARTBEAT

Sent periodically by the EA to signal liveness.

```json
{"type": "heartbeat", "timestamp": "<broker_time_iso>"}
```

### ACCOUNT_INFO

Account details, sent on connection and periodically.

```json
{
  "type": "account_info",
  "account_number": 12345678,
  "broker_name": "CFI",
  "balance": 10000.00,
  "equity": 10000.00,
  "margin": 0.00,
  "currency": "USD"
}
```

### SYMBOLS

Full list of available symbols, sent on request or connection.

```json
{
  "type": "symbols",
  "symbols": [
    {"name": "EURUSD", "trading_permitted": true},
    {"name": "GBPUSD", "trading_permitted": true}
  ]
}
```

### CONTRACT_SPEC

Contract specification for a requested symbol.

```json
{
  "type": "contract_spec",
  "symbol": "EURUSD",
  "digits": 5,
  "point": 0.00001,
  "tick_size": 0.00001,
  "tick_value": 1.0,
  "contract_size": 100000.0,
  "volume_min": 0.01,
  "volume_max": 500.0,
  "volume_step": 0.01,
  "min_stop_distance": 0,
  "trading_permissions": "FULL",
  "margin_requirement": 1000.0,
  "commission": 0.0,
  "swap_long": -1.5,
  "swap_short": 0.5
}
```

## Message Types (Backend → EA)

### REQUEST_SYMBOLS

Request full symbol list.

```json
{"type": "request_symbols"}
```

### REQUEST_CONTRACT_SPEC

Request contract spec for a specific symbol.

```json
{"type": "request_contract_spec", "symbol": "EURUSD"}
```

## Error Handling

- Malformed messages (invalid JSON, missing `type` field, unknown type)
  are logged and discarded by the receiver. The connection is NOT
  closed on a single malformed message.
- Missing required fields in a typed message cause that message to be
  rejected. The receiver logs the error and continues.
- Socket errors (broken pipe, timeout, reset) trigger connection state
  transition to DISCONNECTED.

## Constraints

- All numeric values use their natural JSON types (integer or float).
- Timestamps use ISO 8601 format.
- Symbol names are broker-specific strings, not canonical names.
- This contract covers Phase 2 (read-only). Order-related messages
  will be added in Phase 5 when the connector gains write capability.
