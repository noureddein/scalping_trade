# Tasks: Phase 6 — Dashboard

**Input**: Design documents from `specs/007-dashboard/`

**Prerequisites**: plan.md, spec.md, data-model.md, contracts/dashboard-api.md, research.md, quickstart.md

**Note**: Phase 6 builds an independent monitoring and configuration dashboard. The dashboard
reads backend state and sends configuration commands. It is NOT in the execution path — the
backend continues operating if the dashboard is unavailable. Single operator, localhost only.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1–US6)
- Include exact file paths in descriptions

---

## Phase 1: Setup

**Purpose**: Dashboard package structure and shared types

- [x] T001 Create the dashboard subpackage directory at src/scalping_core/dashboard/ with __init__.py
- [x] T002 Create migration 009_dashboard_tables.sql in migrations/ adding two tables: (1) audit_log — entry_id uuid PK, account_id string FK NOT NULL, parameter_name string NOT NULL, old_value string (JSON-encoded) NOT NULL, new_value string (JSON-encoded) NOT NULL, change_source string NOT NULL, operator_id string NOT NULL, created_at timestamptz NOT NULL; (2) pair_configuration — pair_id uuid PK, canonical_pair string UNIQUE NOT NULL, broker_symbol string NOT NULL, trading_enabled boolean NOT NULL DEFAULT true, created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: HTTP API framework and SSE infrastructure that all stories depend on

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [x] T003 Implement HTTP API server in src/scalping_core/dashboard/api.py: aiohttp application bound to 127.0.0.1 (localhost only), route registration for all endpoints from contracts/dashboard-api.md, static file serving for src/static/dashboard/. Register an in-process event bus (asyncio.Queue-based, keyed by event type) that backend modules publish to and the SSE stream subscribes from. Backend continues operating independently if dashboard is unavailable (FR-010). Return 503 on backend state unavailability
- [x] T004 Implement Server-Sent Events stream in src/scalping_core/dashboard/live_feed.py: GET /api/stream endpoint per contracts/dashboard-api.md. Event types: overview, spread, position, risk-state, pair-update. Each event includes an id field for reconnection. Client sends Last-Event-ID on reconnect; server replays missed events or sends full state if ID too old. Heartbeat comment line every 15 seconds (FR-011)
- [x] T005 Implement audit logging in src/scalping_core/dashboard/audit_log.py: persist AuditLogEntry atomically with every configuration change (FR-008). Fields: entry_id (uuid), account_id (FK NOT NULL), parameter_name (canonical config key NOT NULL), old_value (JSON NOT NULL), new_value (JSON NOT NULL), change_source ("dashboard" NOT NULL), operator_id (NOT NULL), created_at (timestamptz NOT NULL). Write to PostgreSQL audit_log table from migration 007

**Checkpoint**: HTTP API server, SSE stream, and audit logging ready

---

## Phase 3: User Story 1 — View Trading Overview (Priority: P1) 🎯 MVP

**Goal**: Display all 11 overview fields with near real-time updates

**Independent Test**: Start dashboard + backend → verify all fields display and update on state changes

- [x] T006 [US1] Implement GET /api/overview endpoint in src/scalping_core/dashboard/api.py: compose DashboardState from existing Phase 2–5 data — trading_status (connection + daily risk state), broker_name (AccountInfo.broker_name), account_id (AccountInfo.login), daily_net_pnl (DailyRiskState.net_pnl), daily_profit_limit (DailyRiskState.profit_limit), daily_loss_limit (DailyRiskState.loss_limit), open_positions_count (count Position status=OPEN), trades_today (count OrderIntent completed today), win_count (positions with realized_pnl > 0 today), loss_count (positions with realized_pnl <= 0 today), total_spread_costs (sum spread costs today), account_equity (latest from broker). Return 503 if backend unavailable
- [x] T007 [US1] Implement overview SSE event in src/scalping_core/dashboard/live_feed.py: emit "overview" event on P/L change, trade completion, or state change. Include full DashboardState JSON
- [x] T008 [US1] Create static frontend for overview panel at src/static/dashboard/index.html: display all 11 fields, connect to SSE stream, auto-update on events. Show disconnected indicator when SSE drops (FR-009). Mark data as potentially stale on reconnect until fresh state arrives
- [x] T009 [US1] Write unit tests in tests/test_dashboard_api.py: test GET /api/overview returns all 11 fields, test 503 when backend unavailable, test PROFIT_LOCKED/LOSS_LOCKED prominently shown in trading_status, test values update on trade completion

**Checkpoint**: Overview panel displays all fields and updates in near real-time

---

## Phase 4: User Story 2 — Manage Forex Pairs (Priority: P1)

**Goal**: View, add, remove, enable/disable pairs with protection against removing active pairs

**Independent Test**: Add pair → verify appears; disable → verify signals stop; remove with position → verify blocked

- [x] T010 [US2] Implement pair management endpoints in src/scalping_core/dashboard/api.py: GET /api/pairs (return all PairView objects with 9 fields from §13.2: canonical_pair, broker_symbol, trading_enabled, current_spread, average_spread, maximum_spread, spread_status, active_position, trading_permission), POST /api/pairs (add pair, validate not duplicate, audit log), PUT /api/pairs/{pair}/enabled (enable/disable, audit log), DELETE /api/pairs/{pair} (remove pair, reject with 409 if active position or unresolved order exists per FR-012, audit log)
- [x] T011 [US2] Implement pair-update SSE event in src/scalping_core/dashboard/live_feed.py: emit "pair-update" event on pair config change (add/remove/enable/disable). Include full PairView JSON
- [x] T012 [US2] Write unit tests in tests/test_dashboard_api.py: test GET /api/pairs returns all 9 fields, test POST creates pair and logs, test PUT enables/disables and logs, test DELETE blocked on active position (409), test DELETE succeeds when no position

**Checkpoint**: Pair management works with protection against removing active pairs

---

## Phase 5: User Story 3 — Monitor Live Spread (Priority: P1)

**Goal**: Display 9 spread fields per pair with near real-time updates

**Independent Test**: Feed ticks → verify spread fields update; trigger spike → verify timer appears

- [x] T013 [US3] Implement GET /api/pairs/{pair}/spread endpoint in src/scalping_core/dashboard/api.py: return SpreadMonitorView with 9 fields from §13.3 — current_spread, average_spread, maximum_spread, spread_trend (from Phase 3 SpreadSnapshot.trend), spread_volatility (Phase 3 SpreadSnapshot.volatility property → stddev_pips), manual_threshold (SpreadConfig.manual_max_spread), dynamic_threshold (SpreadConfig.adaptive_threshold), stability_timer (MarketHealthState timer status), trading_permission (SpreadSnapshot.entry_eligible). Return 404 if pair not found
- [x] T014 [US3] Implement spread SSE event in src/scalping_core/dashboard/live_feed.py: emit "spread" event on each tick received for a pair. Include PairView + SpreadMonitorView JSON
- [x] T015 [US3] Write unit tests in tests/test_dashboard_live_feed.py: test spread event emitted on tick, test all 9 fields present, test stability timer appears on spread spike, test trading_permission changes to blocked during spike

**Checkpoint**: Spread monitor displays all fields and updates on each tick

---

## Phase 6: User Story 4 — Configure Risk Controls (Priority: P1)

**Goal**: Modify 8 risk parameters with validation and audit logging

**Independent Test**: Change daily loss limit → verify validated, applied, logged; submit invalid → verify rejected

- [x] T016 [US4] Implement GET /api/risk-config endpoint in src/scalping_core/dashboard/api.py: return RiskConfigurationSet with all 8 parameters from §13.4 — daily_profit_limit (positive Decimal), daily_loss_limit (negative Decimal), max_loss_per_trade (positive, <= abs(daily_loss_limit)), lot_size (0.01 fixed, editable=false), take_profit_range (positive Decimal range), spread_thresholds (positive Decimals), trading_schedule (editable=false until §19#3/#4 approved), position_limits (positive int >= 1). Mark read-only fields with editable=false
- [x] T017 [US4] Implement PUT /api/risk-config/{parameter} endpoint in src/scalping_core/dashboard/api.py: validate per-parameter rules from data-model.md RiskConfigurationSet. Return 400 with error message on invalid value. Return 403 on read-only parameter (lot_size, trading_schedule). On success: apply change for next evaluation cycle (no restart needed), write AuditLogEntry atomically (FR-008), return old_value/new_value/applied=true
- [x] T018 [US4] Write unit tests in tests/test_dashboard_audit.py: test valid config change is applied and logged (SC-004), test invalid value rejected (400), test read-only parameter rejected (403), test audit log contains timestamp/old_value/new_value/operator_id, test change takes effect next cycle without restart

**Checkpoint**: Risk controls are modifiable with full validation and audit trail

---

## Phase 7: User Story 5 — View Open Positions (Priority: P1)

**Goal**: Display all 11 position fields with near real-time floating P/L updates

**Independent Test**: Open position → verify all fields; price changes → verify floating P/L updates

- [x] T019 [US5] Implement GET /api/positions endpoint in src/scalping_core/dashboard/api.py: return array of PositionView objects with all 11 fields from §13.5 — pair, direction, entry_price, current_price (latest tick), lot_size, floating_pnl (calculated from entry vs current), stop_loss, take_profit, holding_duration (now - entry_time), strategy (from OrderIntent.strategy_name), exit_status (Position.status). Return empty array (not error) when no open positions
- [x] T020 [US5] Implement position SSE event in src/scalping_core/dashboard/live_feed.py: emit "position" event on position open, close, and price update. Include full PositionView JSON
- [x] T021 [US5] Write unit tests in tests/test_dashboard_api.py: test all 11 fields present, test floating P/L updates with price change, test empty array when no positions (not error), test position removed from active list on close

**Checkpoint**: Positions panel shows all fields with live P/L updates

---

## Phase 8: User Story 6 — Access Additional Modules (Priority: P2)

**Goal**: Trading history, risk events, system logs, broker accounts, emergency stop

**Independent Test**: Activate emergency stop → verify DRAINING transition and entries blocked

- [x] T022 [US6] Implement emergency stop in src/scalping_core/dashboard/emergency.py: POST /api/emergency-stop per contracts/dashboard-api.md. Require {"confirm": true} (reject 400 without it). Transition system to DRAINING via existing Phase 5 daily risk state machine (FR-007). Return 409 if already DRAINING or DISABLED. Log as RiskEvent. Emergency stop must complete within 1 second (SC-005)
- [x] T023 [US6] Implement secondary read endpoints in src/scalping_core/dashboard/api.py: GET /api/history (closed positions with P/L), GET /api/risk-events (reverse chronological, ?limit=N&offset=M pagination), GET /api/audit-log (?limit=N&offset=M pagination), GET /api/system-logs (?limit=N&level=ERROR|WARN|INFO filtering)
- [x] T024 [US6] Implement risk-state SSE event in src/scalping_core/dashboard/live_feed.py: emit "risk-state" event on DailyRiskState transitions (ACTIVE→PROFIT_LOCKED, etc.)
- [x] T025 [US6] Write unit tests in tests/test_dashboard_emergency.py: test emergency stop transitions to DRAINING (SC-005), test 409 when already draining, test 400 without confirm=true, test RiskEvent logged, test entries blocked after activation
- [x] T026 [US6] Write unit tests in tests/test_dashboard_api.py: test GET /api/history returns closed positions with P/L, test GET /api/risk-events pagination, test GET /api/audit-log pagination, test GET /api/system-logs level filtering

**Checkpoint**: All secondary modules accessible; emergency stop functional

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: SSE reconnection, disconnection handling, end-to-end validation

- [x] T027 Implement SSE reconnection handling in src/scalping_core/dashboard/live_feed.py: on client reconnect with Last-Event-ID, replay missed events or send full state refresh. Verify no events duplicated, missed, or misordered on reconnection (FR-011, SC-006)
- [x] T028 Implement disconnection indicator in src/static/dashboard/index.html: when SSE connection drops, show "backend disconnected" indicator prominently (FR-009), disable configuration controls, mark all displayed data as potentially stale. On reconnect, re-sync and remove stale indicators
- [x] T029 Write integration tests in tests/test_dashboard_live_feed.py: test SSE reconnection replays missed events, test no duplicate/missing events, test heartbeat keeps connection alive, test dashboard failure does not affect backend operation (SC-007)
- [x] T030 Run quickstart.md validation scenarios end-to-end and record PASS/FAIL evidence

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — T001/T002 can start immediately
- **Foundational (Phase 2)**: Depends on Setup — T003–T005 need package structure
- **User Stories (Phases 3–8)**: All depend on Foundational (HTTP API + SSE + audit)
  - US1 can start first (overview is the primary panel)
  - US2, US3, US5 can run in parallel after Foundational (different endpoints, different files)
  - US4 depends on audit logging (T005)
  - US6 depends on Foundational only (emergency stop uses existing Phase 5 state machine)
- **Polish (Phase 9)**: Depends on all user stories

### User Story Dependencies

- **US1 (P1)**: No dependencies on other stories
- **US2 (P1)**: No dependencies on other stories
- **US3 (P1)**: No dependencies on other stories
- **US4 (P1)**: No dependencies on other stories
- **US5 (P1)**: No dependencies on other stories
- **US6 (P2)**: No dependencies on other stories

### Parallel Opportunities

- US1, US2, US3, US4, US5 can all run in parallel (different endpoints, mostly different files)
- US6 can run in parallel with P1 stories
- T006/T010/T013/T016/T019 are all in api.py but touch different endpoints — sequential within file

---

## Parallel Example: Multiple Panels

```bash
# After Foundational, start panels in parallel:
# US1: T006-T009 (overview panel)
# US3: T013-T015 (spread monitor — different files)
# US5: T019-T021 (positions panel — different endpoints)
# US6: T022-T026 (emergency stop in emergency.py — different file)
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete T001–T002 (Setup: package + migration)
2. Complete T003–T005 (Foundational: API server + SSE + audit)
3. Complete T006–T009 (US1: overview panel)
4. **STOP and VALIDATE**: Overview displays all 11 fields and updates live
5. Proceed to US2–US6

### Incremental Delivery

1. Setup + Foundational → API server and SSE ready
2. US1 (T006–T009) → overview panel works
3. US2 + US3 + US5 (parallel: T010–T015, T019–T021) → pairs, spread, positions
4. US4 (T016–T018) → risk configuration with audit
5. US6 (T022–T026) → secondary modules and emergency stop
6. Polish (T027–T030) → reconnection, disconnection, end-to-end

---

## Notes

- Dashboard is independent from trading backend — failure does not affect execution (FR-010)
- Single operator, localhost only — no multi-user auth for pilot
- AuditLogEntry is the only new persisted entity; all other views compose from Phase 2–5 tables
- Lot size (0.01) is read-only in dashboard; trading schedule requires §19#3/#4 approval
- Spread stability timer (60s) displayed as read-only; configurability is future enhancement
- Emergency stop uses existing Phase 5 DRAINING state transition
- SSE events include id for reconnection; heartbeat every 15s

---

## Phase 10: Convergence

- [x] T031 Implement GET /api/broker-accounts, GET /api/strategy-performance, and GET /api/execution-stats endpoints in src/scalping_core/dashboard/api.py: broker-accounts returns AccountInfo fields from Phase 2; strategy-performance returns aggregated win/loss/P&L per strategy from completed OrderIntents; execution-stats returns order state distribution counts. Add corresponding unit tests in tests/test_dashboard_api.py per FR-006 (partial)
- [x] T032 Add cross-validation in update_risk_config for max_loss_per_trade: reject with 400 if value > abs(current daily_loss_limit). Read current daily_loss_limit from backend risk config before validating per data-model.md RiskConfigurationSet (partial)
- [x] T033 Wrap config change + audit log write in a single backend method call to ensure atomicity per FR-008/SC-004. In api.py update_risk_config, call backend.update_risk_config_with_audit() (or equivalent) that performs both operations; fall back to current two-step approach if method unavailable (partial)
