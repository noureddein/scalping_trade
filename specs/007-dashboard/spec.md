# Feature Specification: Phase 6 — Dashboard

**Feature Branch**: `007-dashboard`

**Created**: 2026-11-10

**Status**: Draft

**Input**: User description: "Create a specification for the Phase 6: Dashboard"

**Master Plan Reference**: Phase 6 (line 1104), §13 Dashboard Requirements, §13.1–13.6

## User Scenarios & Testing

### User Story 1 - View Trading Overview (Priority: P1)

The operator views a real-time overview of the system's current state:
trading status, selected broker and account, daily net P/L, daily
profit and loss limits, open positions count, trades today, win/loss
statistics, total spread costs, and current account equity. Data
updates in near real-time without manual refresh.

**Why this priority**: The overview is the operator's primary
situational awareness tool. Without it, the operator cannot make
informed decisions about the system's health.

**Independent Test**: Start the dashboard with the backend running.
Verify all overview fields display correct values and update when
backend state changes.

**Acceptance Scenarios**:

1. **Given** the system is running with an active broker connection,
   **When** the overview loads, **Then** all 11 fields from §13.1 are
   displayed with current values.
2. **Given** a trade completes, **When** the overview updates, **Then**
   daily P/L, trade count, and win/loss statistics reflect the change.
3. **Given** no broker connection, **When** the overview loads, **Then**
   the status clearly indicates disconnected state.
4. **Given** PROFIT_LOCKED or LOSS_LOCKED state, **When** the overview
   loads, **Then** the trading status prominently shows the lock.

---

### User Story 2 - Manage Forex Pairs (Priority: P1)

The operator views all configured pairs with their canonical name,
broker symbol, enabled/disabled status, current spread, average
spread, maximum spread, spread status, active position indicator, and
trading permission. The operator can add, remove, enable, and disable
pairs.

**Why this priority**: Pair management controls which instruments the
system trades. Incorrect pair configuration can lead to trading on
unwanted pairs or missing opportunities.

**Independent Test**: Add a new pair, verify it appears in the list.
Disable a pair, verify it is marked disabled and the system stops
generating signals for it.

**Acceptance Scenarios**:

1. **Given** the pairs list, **When** viewed, **Then** all 9 fields
   from §13.2 are displayed per pair.
2. **Given** a new pair, **When** added via the dashboard, **Then** it
   appears in the list and is available for trading if enabled.
3. **Given** an active pair, **When** disabled, **Then** the system
   stops generating signals for it; existing positions are unaffected.
4. **Given** a pair with an active position, **When** removal is
   attempted, **Then** the dashboard prevents removal and displays a
   warning.

---

### User Story 3 - Monitor Live Spread (Priority: P1)

The operator monitors live spread data per pair: current spread,
average spread, maximum spread, spread trend, spread volatility,
manual threshold, dynamic threshold, stability timer status, and
trading permission. Data updates in near real-time.

**Why this priority**: Spread monitoring is critical for understanding
market conditions and verifying that spread protection gates are
functioning correctly.

**Independent Test**: Feed ticks with known spreads. Verify all spread
fields update correctly and stability timer behaves as expected.

**Acceptance Scenarios**:

1. **Given** an active pair with live ticks, **When** the spread
   monitor is viewed, **Then** all 9 fields from §13.3 display
   current values.
2. **Given** a spread spike, **When** observed, **Then** the display
   shows the spike, trading permission changes to blocked, and the
   stability timer appears.
3. **Given** 60 seconds of stable spread after a spike, **When** the
   timer completes, **Then** trading permission returns to allowed.

---

### User Story 4 - Configure Risk Controls (Priority: P1)

The operator modifies risk parameters: daily profit limit, daily loss
limit, maximum loss per trade, lot size, take profit range, spread
thresholds, trading schedule, and position limits. All changes are
validated before applying and logged for audit.

**Why this priority**: Risk controls are the primary safety mechanism.
Configuration changes must be validated to prevent accidental
misconfiguration that could expose the account to unintended risk.

**Independent Test**: Change the daily loss limit. Verify the change
is validated, applied, and logged. Verify invalid values are rejected.

**Acceptance Scenarios**:

1. **Given** the risk controls panel, **When** the operator changes
   the daily profit limit from $15 to $20, **Then** the change is
   validated, applied, and a log entry is created.
2. **Given** an invalid value (e.g., negative lot size), **When**
   submitted, **Then** the dashboard rejects the change with a clear
   error message.
3. **Given** a configuration change, **When** applied, **Then** it
   takes effect for the next evaluation cycle without requiring a
   system restart.
4. **Given** the audit log, **When** reviewed, **Then** all
   configuration changes are recorded with timestamp, old value, new
   value, and operator identity.

---

### User Story 5 - View Open Positions (Priority: P1)

The operator views all open positions with: pair, direction, entry
price, current price, lot size, floating P/L, stop loss, take profit,
holding duration, strategy name, and exit status. Data updates in
near real-time.

**Why this priority**: Position visibility is essential for the
operator to monitor active trades and intervene if needed.

**Independent Test**: Open a position (via test harness). Verify all
fields are displayed and floating P/L updates with price changes.

**Acceptance Scenarios**:

1. **Given** an open position, **When** the positions panel is viewed,
   **Then** all 11 fields from §13.5 are displayed.
2. **Given** a price change, **When** the display updates, **Then**
   floating P/L reflects the new price.
3. **Given** no open positions, **When** viewed, **Then** the panel
   displays an empty state (not an error).
4. **Given** a position that closes, **When** the display updates,
   **Then** the position moves to history or is removed from the
   active list.

---

### User Story 6 - Access Additional Modules (Priority: P2)

The operator accesses secondary panels: broker accounts management,
trading history, strategy performance summaries, execution statistics,
system logs, risk events, and an emergency stop. The emergency stop
immediately blocks all new entries and transitions the system to
DRAINING state.

**Why this priority**: Secondary modules provide operational depth.
The emergency stop is a critical safety feature that must be instantly
accessible.

**Independent Test**: Activate the emergency stop. Verify the system
transitions to DRAINING and all new entries are blocked.

**Acceptance Scenarios**:

1. **Given** the emergency stop button, **When** activated, **Then**
   the system transitions to DRAINING and new entries are blocked.
2. **Given** the trading history panel, **When** viewed, **Then**
   closed positions are listed with entry/exit details and P/L.
3. **Given** the risk events panel, **When** viewed, **Then** all
   risk events (limit triggers, locks, resets, operator resolutions)
   are displayed chronologically.
4. **Given** the system logs panel, **When** viewed, **Then** recent
   system events are displayed with severity and timestamp.

---

### Edge Cases

- What happens if the backend is unreachable? The dashboard displays
  a clear "backend disconnected" indicator and disables configuration
  changes. Existing displayed data is marked as potentially stale.
- What happens if the dashboard disconnects and reconnects to the
  live data feed? It re-syncs state without duplicating or missing
  updates.
- What happens if two operators modify the same setting concurrently?
  This is a single-operator system (§14.2); concurrent dashboard
  access is not a supported scenario. The assumption is one operator.
- What happens if the operator enters a risk control value that
  conflicts with an existing position (e.g., lowering the loss limit
  below current floating loss)? The dashboard warns but allows the
  change — the new limit applies to future evaluations, not
  retroactively to open positions.
- What happens if dashboard failure occurs during active trading?
  The backend continues operating independently. The dashboard is a
  monitoring/configuration tool, not part of the execution path.
  Position protection and risk enforcement are backend responsibilities.

## Requirements

### Functional Requirements

- **FR-001**: The dashboard MUST display all 11 overview fields from
  §13.1 with near real-time updates.
- **FR-002**: The dashboard MUST display all 9 pair management fields
  from §13.2 and allow adding, removing, enabling, and disabling
  pairs.
- **FR-003**: The dashboard MUST display all 9 live spread monitor
  fields from §13.3 with near real-time updates.
- **FR-004**: The dashboard MUST display all 8 risk control parameters
  from §13.4, of which 6 are editable (lot_size and trading_schedule
  are read-only for pilot), with validation and audit logging for
  editable parameters.
- **FR-005**: The dashboard MUST display all 11 position fields from
  §13.5 with near real-time updates.
- **FR-006**: The dashboard MUST provide access to the 7 additional
  modules from §13.6: broker accounts, trading history, strategy
  performance, execution statistics, system logs, risk events, and
  emergency stop.
- **FR-007**: The emergency stop MUST immediately transition the
  system to DRAINING and block all new entries.
- **FR-008**: All configuration changes MUST be validated before
  applying and logged with timestamp, old value, new value, and
  operator identity.
- **FR-009**: The dashboard MUST clearly indicate disconnected,
  stale, or error states rather than displaying outdated data as
  current.
- **FR-010**: The dashboard MUST operate independently from the
  trading backend. Dashboard failure MUST NOT affect position
  protection, risk enforcement, or trade execution.
- **FR-011**: The dashboard MUST handle live update reconnection
  without duplicating, missing, or misordering updates.
- **FR-012**: The dashboard MUST prevent removal of a pair with an
  active position or unresolved order.

### Key Entities

- **Dashboard View**: A real-time representation of system state
  derived from backend data (positions, P/L, spreads, risk state).
- **Risk Configuration**: Operator-modifiable risk parameters with
  validation rules and audit trail.
- **Audit Log Entry**: A record of every configuration change with
  timestamp, old/new values, and operator identity.
- **Emergency Stop**: A one-click control that transitions the system
  to DRAINING state.

## Success Criteria

### Measurable Outcomes

- **SC-001**: All dashboard panels load and display correct data
  within 2 seconds of navigation.
- **SC-002**: Live data updates are reflected on the dashboard within
  1 second of the backend state change.
- **SC-003**: All configuration changes are validated and either
  accepted or rejected with a clear message within 1 second.
- **SC-004**: Every configuration change is recorded in the audit log
  with no gaps in 100% of test scenarios.
- **SC-005**: The emergency stop transitions the system to DRAINING
  within 1 second of activation.
- **SC-006**: Dashboard disconnection and reconnection recovers
  accurate state display without manual intervention.
- **SC-007**: Dashboard failure does not affect backend operation in
  any test scenario (backend continues trading independently).

## Assumptions

- This is a single-operator dashboard. No multi-user access control
  or role-based permissions are needed for the pilot.
- The dashboard is independent from the trading backend. It reads
  state and sends configuration commands but is not in the execution
  path.
- The dashboard connects to the backend; the backend does not depend
  on the dashboard being available.
- "Near real-time" means updates within 1 second of the backend
  state change, not tick-by-tick sub-millisecond latency.
- Strategy performance summaries are aggregated views of completed
  trades, not live optimization metrics.
- The spread stability timer (60 seconds) is displayed as read-only
  in Phase 6. Configurability of the timer value is a future
  enhancement.
- Trading schedule configuration (§13.4) requires owner-approved
  session/news policies (§19#3/#4) before it can be populated with
  actual values.
