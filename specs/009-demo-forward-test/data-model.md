# Data Model: Phase 8 — Demo Forward Test

**Date**: 2026-11-10

## Entities

### DemoScopeApproval

Owner-recorded authorization for Demo order submission. Gate entity —
must exist before any order is submitted.

| Field | Type | Constraints |
|-------|------|-------------|
| approval_id | uuid | PK |
| account_id | string | FK to TradingAccount; NOT NULL |
| account_type | string | Must be "DEMO"; NOT NULL; CHECK |
| approved_pair | string | FK to CanonicalSymbol; NOT NULL |
| approved_lot_size | decimal | Must match pilot lot (0.01); NOT NULL |
| start_time | timestamp | When approval becomes active; NOT NULL |
| end_time | timestamp | When approval expires; NOT NULL |
| stop_conditions | string | JSON stop criteria; NOT NULL |
| monitoring_requirements | string | JSON monitoring spec; NOT NULL |
| status | enum | ACTIVE, EXPIRED, REVOKED; NOT NULL |
| approved_by | string | Owner identifier; NOT NULL |
| approved_at | timestamp | NOT NULL |
| revoked_at | timestamp | Nullable; set on revocation |
| revocation_reason | string | Nullable |

**Constraints**:
- At most one ACTIVE approval at a time (partial unique).
- account_type CHECK = 'DEMO'.
- end_time > start_time.

**State transitions**:
- ACTIVE → EXPIRED: automatic when current time > end_time
- ACTIVE → REVOKED: owner action

### ForwardTestSession

A bounded period of Demo trading.

| Field | Type | Constraints |
|-------|------|-------------|
| session_id | uuid | PK |
| approval_id | uuid | FK to DemoScopeApproval; NOT NULL |
| started_at | timestamp | NOT NULL |
| ended_at | timestamp | Nullable; set on session end |
| end_reason | string | "duration_expired", "owner_revoked", "emergency_stop", "manual_stop"; nullable |
| total_signals | integer | Count of all signals generated; NOT NULL; default 0 |
| total_entries_attempted | integer | NOT NULL; default 0 |
| total_entries_rejected | integer | NOT NULL; default 0 |
| total_fills | integer | NOT NULL; default 0 |
| total_rejections | integer | NOT NULL; default 0 |
| net_pnl | decimal | After all costs; nullable |
| total_costs | decimal | Sum of all cost components; nullable |

### ForwardTestEvent

High-frequency event log for every signal and decision during Demo
trading. Separate from RiskEvent to prevent table bloat.

| Field | Type | Constraints |
|-------|------|-------------|
| event_id | uuid | PK |
| session_id | uuid | FK to ForwardTestSession; NOT NULL |
| event_type | enum | See event types below; NOT NULL |
| timestamp | timestamp | When event occurred; NOT NULL |
| pair | string | FK to CanonicalSymbol; NOT NULL |
| detail | string | JSON structured detail; NOT NULL |
| related_intent_id | uuid | FK to OrderIntent; nullable |
| related_signal_id | uuid | Nullable |

**Event types**: SIGNAL_GENERATED, SIGNAL_REJECTED, ENTRY_APPROVED,
ENTRY_REJECTED (with reason code), ORDER_SUBMITTED, ORDER_FILLED,
ORDER_REJECTED, ORDER_TIMEOUT, FILL_DISCREPANCY, COST_RECORDED,
SPREAD_AT_DECISION, LATENCY_RECORDED, DURATION_EXPIRED,
APPROVAL_REVOKED.

### ExecutionDiscrepancy

Records differences between expected and actual execution.

| Field | Type | Constraints |
|-------|------|-------------|
| discrepancy_id | uuid | PK |
| session_id | uuid | FK to ForwardTestSession; NOT NULL |
| intent_id | uuid | FK to OrderIntent; NOT NULL |
| expected_price | decimal | Reference price at submission; NOT NULL |
| actual_price | decimal | Broker fill price; NOT NULL |
| slippage_pips | decimal | Difference in pips; NOT NULL |
| submission_time | timestamp | When order was sent; NOT NULL |
| fill_time | timestamp | When broker confirmed fill; NOT NULL |
| latency_ms | integer | fill_time - submission_time; NOT NULL |
| direction | enum | BUY or SELL; NOT NULL |

### ForwardTestReport

Summary report with mandatory limitations and disclaimers.

| Field | Type | Constraints |
|-------|------|-------------|
| report_id | uuid | PK |
| session_id | uuid | FK to ForwardTestSession; NOT NULL; UNIQUE |
| sample_size | integer | Number of completed trades; NOT NULL |
| sample_sufficient | boolean | Owner-defined threshold met; NOT NULL |
| net_pnl | decimal | After all costs; NOT NULL |
| gross_pnl | decimal | Before costs; NOT NULL |
| total_spread_cost | decimal | NOT NULL |
| total_commission | decimal | NOT NULL |
| total_swap | decimal | NOT NULL |
| avg_slippage_pips | decimal | NOT NULL |
| max_drawdown | decimal | NOT NULL |
| win_rate | decimal | Percentage; NOT NULL |
| avg_trade_duration | interval | NOT NULL |
| statistical_warnings | string | JSON array of warning messages; NOT NULL |
| generated_at | timestamp | NOT NULL |

## Relationships

```
DemoScopeApproval 1──* ForwardTestSession
ForwardTestSession 1──* ForwardTestEvent
ForwardTestSession 1──* ExecutionDiscrepancy
ForwardTestSession 1──1 ForwardTestReport
OrderIntent (Phase 5) 1──0..* ForwardTestEvent
OrderIntent (Phase 5) 1──0..1 ExecutionDiscrepancy
```

## Notes

- DemoScopeApproval is the authorization gate. It enforces
  Constitution Principle III by requiring explicit owner approval
  scoped to Demo only.
- ForwardTestEvent is high-frequency and separate from RiskEvent
  (Phase 5) to prevent operational table bloat.
- ExecutionDiscrepancy captures real slippage data that feeds back
  into Phase 7 backtest calibration.
- Migration 009 adds these tables. It does not modify existing
  Phase 2–7 tables.
- The ForwardTestReport always includes statistical_warnings. An
  empty array means no warnings — but the "results do not authorize
  live trading" disclaimer is always present in the report text.
