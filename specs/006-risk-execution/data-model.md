# Data Model: Phase 5 — Risk and Execution

**Date**: 2026-11-10

## Entities

### OrderIntent

Durable record of intent to submit an order. Created before broker
contact.

| Field | Type | Constraints |
|-------|------|-------------|
| intent_id | uuid | PK |
| pair | string | FK to CanonicalSymbol; NOT NULL |
| account_id | string | FK to TradingAccount; NOT NULL |
| direction | enum | BUY or SELL; NOT NULL |
| lot_size | decimal | Fixed 0.01 for pilot; positive; NOT NULL |
| entry_price_ref | decimal | Reference price at signal time; NOT NULL |
| stop_loss_price | decimal | Calculated SL; NOT NULL |
| take_profit_price | decimal | Calculated TP; NOT NULL |
| estimated_loss | decimal | Pre-trade risk estimate; NOT NULL |
| strategy_name | string | Which strategy produced the signal; NOT NULL |
| signal_id | uuid | FK to signal recommendation; NOT NULL |
| state | enum | See order state machine below; NOT NULL |
| created_at | timestamp | With timezone; NOT NULL |
| updated_at | timestamp | With timezone; NOT NULL |

**Partial unique constraint**: At most one non-terminal OrderIntent per
pair per account (states: DRAFT, PENDING_SUBMIT, SUBMITTING, SUBMITTED,
UNKNOWN).

### OrderOutcome

Broker response to an order submission.

| Field | Type | Constraints |
|-------|------|-------------|
| outcome_id | uuid | PK |
| intent_id | uuid | FK to OrderIntent; NOT NULL; UNIQUE |
| broker_ticket | string | Broker-assigned order/deal ID; nullable |
| fill_price | decimal | Actual fill price; nullable (if not filled) |
| fill_time | timestamp | Broker-reported fill time; nullable |
| outcome_type | enum | FILLED, REJECTED, CANCELLED, TIMEOUT, UNKNOWN; NOT NULL |
| broker_error | string | Error message if rejected; nullable |
| correlation_token | string | Token used for order matching; nullable |
| recorded_at | timestamp | When backend persisted this; NOT NULL |

### PairReservation

Durable per-pair lock preventing duplicate entries.

| Field | Type | Constraints |
|-------|------|-------------|
| reservation_id | uuid | PK |
| pair | string | FK to CanonicalSymbol; NOT NULL |
| account_id | string | FK to TradingAccount; NOT NULL |
| intent_id | uuid | FK to OrderIntent; NOT NULL |
| status | enum | HELD, RELEASED; NOT NULL |
| acquired_at | timestamp | NOT NULL |
| released_at | timestamp | Nullable; set on release |

**Unique constraint**: At most one HELD reservation per pair per account.

### Position

Record of an open or closed position.

| Field | Type | Constraints |
|-------|------|-------------|
| position_id | uuid | PK |
| pair | string | FK to CanonicalSymbol; NOT NULL |
| account_id | string | FK to TradingAccount; NOT NULL |
| intent_id | uuid | FK to OrderIntent; NOT NULL |
| direction | enum | BUY or SELL; NOT NULL |
| lot_size | decimal | NOT NULL |
| entry_price | decimal | Actual fill price; NOT NULL |
| stop_loss | decimal | NOT NULL |
| take_profit | decimal | NOT NULL |
| status | enum | OPEN, CLOSED, SETTLING; NOT NULL |
| entry_time | timestamp | NOT NULL |
| exit_price | decimal | Nullable; set on close |
| exit_time | timestamp | Nullable; set on close |
| realized_pnl | decimal | Nullable; set on close |
| commission | decimal | Nullable |
| swap | decimal | Nullable |

**Partial unique constraint**: At most one OPEN position per pair per
account.

### DailyRiskState

Per-day risk tracking with state machine.

| Field | Type | Constraints |
|-------|------|-------------|
| risk_state_id | uuid | PK |
| account_id | string | FK to TradingAccount; NOT NULL |
| trading_day | date | Asia/Amman boundary; NOT NULL |
| state | enum | ACTIVE, PROFIT_LOCKED, LOSS_LOCKED, DRAINING, DISABLED; NOT NULL |
| realized_pnl | decimal | Day's realized P/L; NOT NULL; default 0 |
| floating_pnl | decimal | Current unrealized P/L; NOT NULL; default 0 |
| commissions | decimal | Day's total commissions; NOT NULL; default 0 |
| swaps | decimal | Day's total swaps; NOT NULL; default 0 |
| net_pnl | decimal | realized + floating + commissions + swaps; NOT NULL |
| profit_limit | decimal | Configurable; default +15.00; NOT NULL |
| loss_limit | decimal | Configurable; default -5.00; NOT NULL |
| state_changed_at | timestamp | Last state transition; NOT NULL |
| locked_by | string | What triggered the lock; nullable |

**Unique constraint**: One DailyRiskState per account per trading_day.

**State transitions**:
- ACTIVE → PROFIT_LOCKED: net_pnl >= profit_limit
- ACTIVE → LOSS_LOCKED: net_pnl <= loss_limit
- ACTIVE → DRAINING: operator action only
- ACTIVE → DISABLED: operator action only
- PROFIT_LOCKED → ACTIVE: daily reset (Asia/Amman boundary)
- LOSS_LOCKED → ACTIVE: daily reset (Asia/Amman boundary)
- DRAINING → ACTIVE: authorized manual clearing only (survives rollover)
- DISABLED → ACTIVE: authorized manual reactivation only (survives rollover)

### RiskEvent

Auditable record of risk-related decisions and interventions.

| Field | Type | Constraints |
|-------|------|-------------|
| event_id | uuid | PK |
| account_id | string | FK to TradingAccount; NOT NULL |
| event_type | enum | See event types below; NOT NULL |
| detail | string | Structured description; NOT NULL |
| related_intent_id | uuid | FK to OrderIntent; nullable |
| related_position_id | uuid | FK to Position; nullable |
| operator_id | string | Who performed the action; nullable |
| created_at | timestamp | NOT NULL |

**Event types**: ENTRY_REJECTED, LIMIT_TRIGGERED, LOCK_ACTIVATED,
LOCK_RESET, OPERATOR_RESOLUTION, BARRIER_HELD, BARRIER_RELEASED,
RECONCILIATION_START, RECONCILIATION_COMPLETE, FILL_PERSIST_FAILURE,
ADMISSION_HALTED.

### ReconciliationBarrier

Account-wide entry gate for startup reconciliation.

| Field | Type | Constraints |
|-------|------|-------------|
| barrier_id | uuid | PK |
| account_id | string | FK to TradingAccount; NOT NULL |
| status | enum | HELD, RELEASED; NOT NULL |
| reason | string | Why barrier is held; NOT NULL |
| held_at | timestamp | NOT NULL |
| released_at | timestamp | Nullable |
| resolved_by | string | Operator or system; nullable |

## Order State Machine

```
DRAFT → PENDING_SUBMIT → SUBMITTING → SUBMITTED
  ↓          ↓                           ↓
  └──→ CANCELLED ←────────────┌──────────┼──────────┐
                              ↓          ↓          ↓
                           FILLED    REJECTED    UNKNOWN
                                                    ↓
                                          OPERATOR_RESOLVED
```

**Cancellable states**: DRAFT, PENDING_SUBMIT (local cancel on daily
limit trigger or system shutdown). SUBMITTED may be cancelled by broker.
SUBMITTING cannot be cancelled (outcome unknown).

**Blocking states** (pair reserved, entries blocked):
DRAFT, PENDING_SUBMIT, SUBMITTING, SUBMITTED, UNKNOWN

**Terminal states** (reservation released):
FILLED (after position created), REJECTED, CANCELLED, OPERATOR_RESOLVED

## Relationships

```
TradingAccount (Phase 2) 1──* OrderIntent
OrderIntent 1──0..1 OrderOutcome
OrderIntent 1──1 PairReservation
OrderIntent 1──0..1 Position
TradingAccount 1──* DailyRiskState
TradingAccount 1──* RiskEvent
TradingAccount 1──1 ReconciliationBarrier
CanonicalSymbol (Phase 2) 1──* OrderIntent
CanonicalSymbol 1──* PairReservation
CanonicalSymbol 1──* Position
```

## Notes

- All entities are durably persisted in PostgreSQL.
- The order state machine is the central safety mechanism — every
  state transition is logged as a RiskEvent.
- The ReconciliationBarrier is account-wide, not per-pair.
- Currency conversion interface exists but actual source/freshness
  rules are deferred (§19#14).
- Partial-fill handling is deferred (§19#15); schema is compatible
  with future extension.
