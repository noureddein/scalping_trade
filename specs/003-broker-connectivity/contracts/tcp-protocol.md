# TCP Protocol Contract: EA ↔ Backend

**Date**: 2026-11-10

## Transport

- TCP over loopback 127.0.0.1
- One connection per EA instance
- Length-prefixed JSON messages (4-byte big-endian length header
  followed by UTF-8 JSON payload)

## Message Types (EA → Backend)

Every EA message uses the common envelope
`{"type":"<message_type>","data":{...}}`. The Python adapter accepts
only the type names and field shapes described below.

### HEARTBEAT

Sent periodically by the EA to signal liveness.

```json
{"type":"heartbeat","data":{}}
```

### ACCOUNT_INFO

Account details, sent on connection and periodically.

```json
{
  "type": "account_info",
  "data": {
    "login": 12345678,
    "server": "CFI",
    "balance": "10000.00",
    "equity": "10000.00",
    "margin_free": "10000.00",
    "currency": "USD"
  }
}
```

### SYMBOL_LIST

Full list of available symbols, sent on request or connection.

```json
{
  "type": "symbol_list",
  "data": {"symbols": [
    {"name": "EURUSD", "trading_permitted": true},
    {"name": "GBPUSD", "trading_permitted": true}
  ]}
}
```

### CONTRACT_SPEC

Contract specification for a broker symbol included in the discovery snapshot.

```json
{
  "type": "contract_spec",
  "data": {
    "broker_symbol": "EURUSD",
    "digits": 5,
    "point": "0.00001",
    "tick_size": "0.00001",
    "tick_value": "1.0",
    "contract_size": "100000.0",
    "volume_min": "0.01",
    "volume_max": "500.0",
    "volume_step": "0.01",
    "min_stop_distance": "0",
    "trading_permissions": "FULL",
    "margin_initial": "1000.0",
    "commission_per_lot": "0.0",
    "swap_long": "-1.5",
    "swap_short": "0.5"
  }
}
```

## Message Types (Backend → EA)

### REQUEST_SYMBOLS

Request full symbol list.

```json
{"type":"request","data":{"request":"get_symbols"}}
```

### REQUEST_CONTRACT_SPEC

Request one contract spec, or omit `symbol` to refresh all available specs.

```json
{"type":"request","data":{"request":"get_contracts","symbol":"EURUSD"}}
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

- Integer values use JSON integers. Decimal-valued fields are serialized as
  decimal strings to preserve their precision across the MQL5/Python boundary.
- Timestamps use ISO 8601 format.
- Symbol names are broker-specific strings, not canonical names.
- This contract covers Phase 2 (read-only). Order-related messages
  will be added in Phase 5 when the connector gains write capability.
