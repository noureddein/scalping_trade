# Data Model: Phase 2 — Broker Connectivity

**Date**: 2026-11-10

## Entities

### BrokerConnection

Represents the TCP link between the backend and one MT5 EA instance.

| Field | Description | Constraints |
|-------|-------------|-------------|
| state | Connection state | Enum: CONNECTED, DISCONNECTED, RECONNECTING |
| account | Associated account info | Populated only when CONNECTED |
| last_heartbeat | Timestamp of last EA message | Used for disconnect detection |
| remote_address | EA endpoint (127.0.0.1:port) | Loopback only |

**State transitions**:
- DISCONNECTED → RECONNECTING: Backend detects EA connection attempt
- RECONNECTING → CONNECTED: Account info successfully received
- CONNECTED → DISCONNECTED: Heartbeat timeout (≤10s) or socket error
- RECONNECTING → DISCONNECTED: Connection attempt fails or times out

### Account

A single MT5 Demo account's properties.

| Field | Description | Constraints |
|-------|-------------|-------------|
| account_number | MT5 account identifier | Unique, from broker |
| broker_name | Name of the broker | Non-empty string |
| balance | Account balance | Positive decimal |
| equity | Account equity | Decimal |
| margin | Used margin | Non-negative decimal |
| currency | Account base currency | 3-letter currency code |

**Refresh**: Updated on each account info message from the EA.

**Wire-to-domain field mapping**: the existing EA wire names `login`,
`server`, and `margin_free` map to `account_number`, `broker_name`, and
the domain's `margin` field respectively. `margin` therefore means free
margin in this Phase 2 model; it is not a claim about used margin.

### CanonicalSymbol

An internal, broker-independent symbol identifier.

| Field | Description | Constraints |
|-------|-------------|-------------|
| name | Canonical symbol name | Unique, e.g. "EURUSD" |
| is_forex | Whether it is a valid Forex pair | Must be true (gold/commodities excluded) |

### BrokerSymbol

A broker-specific symbol as discovered from the connected account.

| Field | Description | Constraints |
|-------|-------------|-------------|
| broker_name | Broker-specific symbol name | As reported by MT5 |
| trading_permitted | Whether trading is allowed | Boolean from broker |
| account_number | Account it was discovered on | FK to Account |

### SymbolMapping

Associates a canonical symbol with its broker-specific name.

| Field | Description | Constraints |
|-------|-------------|-------------|
| canonical_symbol | Internal symbol reference | FK to CanonicalSymbol |
| broker_symbol | Broker-specific name | FK to BrokerSymbol |
| confirmed_by_owner | Whether the owner approved | Boolean; default false |

**Uniqueness**: One broker symbol per canonical symbol per broker/account.

### ContractSpecification

The broker's trading contract details for a mapped symbol.

| Field | Description | Constraints |
|-------|-------------|-------------|
| symbol_mapping | Which mapping this belongs to | FK to SymbolMapping |
| digits | Price decimal places | Non-negative integer |
| point | Minimum price change | Positive decimal |
| tick_size | Size of one tick | Positive decimal |
| tick_value | Monetary value of one tick | Positive decimal |
| contract_size | Units per lot | Positive decimal |
| volume_min | Minimum trade volume | Positive decimal |
| volume_max | Maximum trade volume | Positive decimal |
| volume_step | Volume increment | Positive decimal |
| min_stop_distance | Minimum SL/TP distance | Non-negative integer (points) |
| trading_permissions | Allowed trade operations | Flags/enum from broker |
| margin_requirement | Margin per lot | Positive decimal |
| commission | Commission per lot | Decimal (may be zero) |
| swap_long | Overnight swap for long | Decimal |
| swap_short | Overnight swap for short | Decimal |

**Validation**: All 15 required fields must be present and valid.
If any field is missing or unparseable, the symbol is marked ineligible
(FR-008).

**Wire-to-domain field mapping**: `margin_initial` maps to
`margin_requirement`, and `commission_per_lot` maps to `commission`.
The current flat per-lot commission field cannot represent tiered or
otherwise conditional commission schedules; such schedules are rejected
as incomplete rather than flattened into an assumed value.

## Relationships

```
BrokerConnection 1──1 Account
Account 1──* BrokerSymbol
CanonicalSymbol 1──* SymbolMapping
BrokerSymbol 1──* SymbolMapping
SymbolMapping 1──1 ContractSpecification
```

## Notes

- Phase 2 stores all entities in memory. Durable PostgreSQL storage is
  Phase 5.
- ContractSpecification has 15 fields (the 13 from §5.2 plus
  swap_long/swap_short, which are the two components of "Swap").
