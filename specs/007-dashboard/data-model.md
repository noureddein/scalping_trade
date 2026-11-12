# Data Model: Phase 6 — Dashboard

**Date**: 2026-11-10

## Entities

### AuditLogEntry

Durable record of every configuration change made through the
dashboard.

| Field | Type | Constraints |
|-------|------|-------------|
| entry_id | uuid | PK |
| account_id | string | FK to TradingAccount; NOT NULL |
| parameter_name | string | Canonical config key; NOT NULL |
| old_value | string | JSON-encoded previous value; NOT NULL |
| new_value | string | JSON-encoded new value; NOT NULL |
| change_source | string | "dashboard" or other origin; NOT NULL |
| operator_id | string | Who made the change; NOT NULL |
| created_at | timestamp | With timezone; NOT NULL |

### DashboardState (read-only view)

Aggregated view of backend state for the dashboard overview panel.
Not a persisted entity — composed at query time from existing Phase
2–5 tables.

| Field | Source |
|-------|--------|
| trading_status | Backend connection state + daily risk state |
| broker_name | AccountInfo.broker_name (Phase 2, broker_types.py) |
| account_id | AccountInfo.login (Phase 2, broker_types.py) |
| daily_net_pnl | DailyRiskState.net_pnl (Phase 5) |
| daily_profit_limit | DailyRiskState.profit_limit (Phase 5) |
| daily_loss_limit | DailyRiskState.loss_limit (Phase 5) |
| open_positions_count | Count of Position where status=OPEN (Phase 5) |
| trades_today | Count of OrderIntent completed today (Phase 5) |
| win_count | Positions with realized_pnl > 0 today (Phase 5) |
| loss_count | Positions with realized_pnl <= 0 today (Phase 5) |
| total_spread_costs | Sum of spread costs today (Phase 3 metrics) |
| account_equity | AccountInfo.equity (Phase 2, broker_types.py) |

### PairView (read-only view)

Per-pair display data composed from existing tables.

| Field | Source |
|-------|--------|
| canonical_pair | CanonicalSymbol (Phase 2) |
| broker_symbol | BrokerSymbol mapping (Phase 2) |
| trading_enabled | Pair configuration flag |
| current_spread | SpreadSnapshot.spread (Phase 3) |
| average_spread | SpreadStatistics.mean (Phase 3) |
| maximum_spread | SpreadStatistics.max (Phase 3) |
| spread_status | SpreadSnapshot.stability_state (Phase 3, spread_engine.py) |
| active_position | Position where status=OPEN for this pair (Phase 5) |
| trading_permission | SpreadSnapshot.entry_eligible + RiskState + regime (combined) |

### SpreadMonitorView (read-only view)

Per-pair live spread monitoring data.

| Field | Source |
|-------|--------|
| current_spread | SpreadSnapshot.spread (Phase 3) |
| average_spread | SpreadStatistics.mean (Phase 3) |
| maximum_spread | SpreadStatistics.max (Phase 3) |
| spread_trend | SpreadSnapshot.trend (Phase 3, spread_engine.py) |
| spread_volatility | SpreadSnapshot.volatility property → stddev_pips (Phase 3) |
| manual_threshold | SpreadConfig.manual_max_spread (Phase 3, spread_engine.py) |
| dynamic_threshold | SpreadConfig.adaptive_threshold (Phase 3, spread_engine.py) |
| stability_timer | MarketHealthState timer (Phase 3, market_data.py) |
| trading_permission | SpreadSnapshot.entry_eligible (Phase 3, spread_engine.py) |

### PositionView (read-only view)

Open position display data.

| Field | Source |
|-------|--------|
| pair | Position.pair (Phase 5) |
| direction | Position.direction (Phase 5) |
| entry_price | Position.entry_price (Phase 5) |
| current_price | Latest tick price (Phase 3) |
| lot_size | Position.lot_size (Phase 5) |
| floating_pnl | Calculated from entry_price vs current_price |
| stop_loss | Position.stop_loss (Phase 5) |
| take_profit | Position.take_profit (Phase 5) |
| holding_duration | now() - Position.entry_time (Phase 5) |
| strategy | OrderIntent.strategy_name (Phase 5) |
| exit_status | Position.status (Phase 5) |

### RiskConfigurationSet

The set of operator-modifiable risk parameters. Stored in existing
DailyRiskState and system configuration. Dashboard provides a
read/write interface.

| Parameter | Source | Validation |
|-----------|--------|------------|
| daily_profit_limit | DailyRiskState.profit_limit | Positive decimal |
| daily_loss_limit | DailyRiskState.loss_limit | Negative decimal |
| max_loss_per_trade | System config | Positive, <= abs(daily_loss_limit) |
| lot_size | System config | 0.01 for pilot (fixed) |
| take_profit_range | System config | Positive decimal range |
| spread_thresholds | SpreadGate config | Positive decimals |
| trading_schedule | System config | Requires §19#3/#4 approval |
| position_limits | System config | Positive integer, >= 1 |

## Relationships

```
TradingAccount (Phase 2) 1──* AuditLogEntry
DailyRiskState (Phase 5) ──> DashboardState (composed)
Position (Phase 5) ──> PositionView (composed)
SpreadSnapshot (Phase 3) ──> SpreadMonitorView (composed)
CanonicalSymbol (Phase 2) ──> PairView (composed)
```

## Notes

- AuditLogEntry is the only new persisted entity. All other
  "entities" are read-only views composed from existing Phase 2–5
  tables at query time.
- Migration 007 adds the `audit_log` table.
- Trading schedule configuration is deferred until §19#3/#4 are
  resolved. The dashboard shows the field as read-only with a
  "requires owner approval" indicator.
- Lot size is fixed at 0.01 for pilot. The dashboard displays it
  but does not allow modification.
