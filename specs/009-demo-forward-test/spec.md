# Feature Specification: Phase 8 — Demo Forward Test

**Feature Branch**: `009-demo-forward-test`

**Created**: 2026-11-10

**Status**: Draft

**Input**: User description: "Create a specification for the Phase 8: Demo forward testing"

**Master Plan Reference**: Phase 8 (line 1262), §14.1 (trading authority), §18 (security/safety)

## User Scenarios & Testing

### User Story 1 - Define Demo Test Scope (Priority: P0)

Before any order submission is enabled, the owner defines and approves
the complete Demo test scope: Demo-only account, pair, lot size,
duration, stop conditions, monitoring requirements, and evidence
record format. No order submission occurs without this explicit
approval.

**Why this priority**: Constitution Principle III prohibits any broker
order submission without explicit owner authorization. This story is
the authorization gate for the entire phase.

**Independent Test**: Present the scope document to the owner. Verify
approval is recorded before any order submission code is activated.

**Acceptance Scenarios**:

1. **Given** no Demo scope approval, **When** order submission is
   attempted, **Then** the system refuses with "no Demo approval."
2. **Given** a scope document, **When** the owner approves it, **Then**
   approval is recorded with date, scope details, and owner identity.
3. **Given** approval for one pair, **When** an order for a different
   pair is attempted, **Then** the system refuses.
4. **Given** an approved duration, **When** the duration expires,
   **Then** the system stops submitting new orders automatically.

---

### User Story 2 - Execute Demo Orders (Priority: P1)

The system submits orders to a Demo account through the existing
Phase 5 execution pipeline. All Phase 5 safety mechanisms are active:
durable order intent, pair reservations, reconciliation barriers,
daily risk limits, and fail-closed behavior. The EA order handler is
enabled for Demo only.

**Why this priority**: This is the first time the system contacts a
broker with order requests. Every safety mechanism must be verified
under real broker conditions.

**Independent Test**: Submit a single order on Demo. Verify the full
lifecycle: intent → reservation → submission → fill/reject → position
or release.

**Acceptance Scenarios**:

1. **Given** an approved Demo scope, **When** the strategy generates a
   valid signal, **Then** the system submits an order to the Demo
   account following the Phase 5 admission sequence.
2. **Given** a submitted order, **When** the broker fills it, **Then**
   the position is created atomically with the fill recording.
3. **Given** a submitted order, **When** the broker rejects it, **Then**
   the rejection is recorded and the reservation released.
4. **Given** a timeout during submission, **When** the outcome is
   unknown, **Then** the system follows the Phase 5 UNKNOWN protocol
   (reservation held, no auto-resubmit).

---

### User Story 3 - Verify Safety Mechanisms Under Real Conditions (Priority: P1)

The owner verifies that all protective mechanisms work with a real
broker: startup reconciliation, protective SL/TP placement, duplicate
protection, daily locks, shutdown/restart recovery, disconnect
behavior, and the emergency stop.

**Why this priority**: Unit tests with mocks cannot prove that safety
mechanisms work under real broker conditions. This is the first
end-to-end validation with actual broker interaction.

**Independent Test**: Kill the backend process during an open
position. Restart. Verify the reconciliation barrier activates, the
position is still tracked, and new entries are blocked until
reconciliation completes.

**Acceptance Scenarios**:

1. **Given** a process restart with an open position, **When** the
   backend starts, **Then** the reconciliation barrier activates and
   new entries are blocked until resolved.
2. **Given** a filled position, **When** verified against the broker
   terminal, **Then** SL and TP are placed as specified.
3. **Given** two signals for the same pair, **When** the first is
   in-flight, **Then** the second is rejected by pair reservation.
4. **Given** daily P/L reaching the loss limit, **When** checked,
   **Then** the system transitions to LOSS_LOCKED and blocks entries.
5. **Given** the emergency stop, **When** activated from the
   dashboard, **Then** the system transitions to DRAINING immediately.
6. **Given** an MT5 disconnect during trading, **When** reconnection
   occurs, **Then** the system recovers state correctly and resumes
   monitoring.

---

### User Story 4 - Record Every Event (Priority: P1)

Every signal, rejected entry, submitted request, broker outcome,
cost, and discrepancy is recorded with full detail. No event is
silently dropped. The evidence record supports post-test analysis.

**Why this priority**: The master plan explicitly requires complete
evidence recording. Selective recording would undermine the validity
of the forward test.

**Independent Test**: Run a test session. Verify the event log
contains entries for every signal generated, every entry decision
(approved or rejected with reason), every broker interaction, and
every cost component.

**Acceptance Scenarios**:

1. **Given** a trading session, **When** a signal is generated, **Then**
   it is recorded regardless of whether it leads to an entry.
2. **Given** a rejected entry, **When** logged, **Then** the specific
   rejection reason is recorded (spread gate, risk limit, pair
   reserved, etc.).
3. **Given** a completed trade, **When** logged, **Then** all cost
   components (spread, commission, swap, slippage) are recorded.
4. **Given** a discrepancy between expected and actual fill, **When**
   detected, **Then** the discrepancy is recorded with both values.

---

### User Story 5 - Prevent False Expectancy Claims (Priority: P1)

The forward test results are reported honestly. No positive expectancy
is inferred from a short or selectively reported sample. The report
explicitly states sample size, duration, and statistical limitations.

**Why this priority**: The master plan warns against inferring
positive expectancy from short Demo tests. This is a governance
requirement to prevent premature live trading authorization.

**Independent Test**: Generate a report from a 5-trade sample.
Verify the report includes a statistical limitation warning.

**Acceptance Scenarios**:

1. **Given** a forward test with fewer than a statistically meaningful
   number of trades, **When** reported, **Then** the report includes a
   "insufficient sample size" warning.
2. **Given** a profitable forward test, **When** reported, **Then** the
   report does not claim "positive expectancy" without statistical
   evidence.
3. **Given** forward test results, **When** reported, **Then** they
   explicitly state that results do not authorize live trading.

---

### Edge Cases

- What happens if the Demo account runs out of margin? The system
  reports margin exhaustion and blocks further entries. It does not
  switch to a different account or request more margin.
- What happens if the Demo server is unavailable? The system follows
  the same disconnect/reconnect protocol as Phase 2. No orders are
  submitted during disconnection. In-flight orders follow the UNKNOWN
  protocol.
- What happens if the approved duration expires with an open position?
  New entries are blocked. The open position continues to be managed
  (SL/TP remain active). The position is not force-closed.
- What happens if the owner revokes Demo approval mid-test? New
  entries are blocked immediately. Open positions continue to be
  managed. The system transitions to a state equivalent to DRAINING.
- What happens if the broker changes Demo account conditions (e.g.,
  spread widening, execution delay)? The system continues to operate
  with the new conditions. All condition changes are visible in the
  recorded evidence (spread snapshots, execution latency).

## Requirements

### Functional Requirements

- **FR-001**: The system MUST refuse all order submissions until the
  owner records explicit Demo scope approval.
- **FR-002**: Demo approval MUST specify: account, pair, lot size,
  maximum duration, stop conditions, and monitoring requirements.
- **FR-003**: Order submissions MUST use the existing Phase 5
  execution pipeline with all safety mechanisms active.
- **FR-004**: The EA order handler MUST be enabled for the approved
  Demo account only. No other account may receive orders.
- **FR-005**: Startup reconciliation MUST work correctly with real
  broker state (not just test doubles).
- **FR-006**: SL and TP MUST be placed as specified and verifiable
  against the broker terminal.
- **FR-007**: Duplicate protection (pair reservation) MUST prevent
  concurrent entries on the same pair under real conditions.
- **FR-008**: Daily risk limits MUST trigger correctly based on
  real broker P/L data.
- **FR-009**: Every signal, entry decision, broker interaction, and
  cost MUST be recorded in the evidence log.
- **FR-010**: No event may be silently dropped from the evidence
  record.
- **FR-011**: Reports MUST NOT claim positive expectancy from
  statistically insufficient samples.
- **FR-012**: Forward test results MUST NOT authorize live trading.
  Separate explicit owner authorization is required for any live
  trading enablement.
- **FR-013**: The system MUST stop submitting new orders when the
  approved duration expires or the owner revokes approval.
- **FR-014**: The emergency stop MUST function correctly during Demo
  forward testing.
- **FR-015**: Disconnect and reconnection behavior MUST be verified
  with the real broker, not just simulated conditions.

### Key Entities

- **Demo Scope Approval**: Owner-recorded authorization specifying
  account, pair, lot, duration, and stop conditions.
- **Forward Test Session**: A bounded period of Demo trading with
  complete evidence recording.
- **Evidence Record**: Complete log of every signal, decision, broker
  interaction, and cost during the test.
- **Forward Test Report**: Summary with honest statistical assessment,
  sample size limitations, and explicit non-authorization statement.

## Success Criteria

### Measurable Outcomes

- **SC-001**: Zero orders are submitted before Demo scope approval is
  recorded.
- **SC-002**: 100% of signals, entry decisions, broker interactions,
  and costs are recorded in the evidence log (verified by log
  completeness audit).
- **SC-003**: All Phase 5 safety mechanisms (reconciliation, pair
  reservation, daily limits, emergency stop) function correctly under
  real broker conditions (verified by deliberate trigger tests).
- **SC-004**: SL and TP values on the broker terminal match the
  system's specified values in 100% of placed orders.
- **SC-005**: Startup recovery correctly reconciles state after a
  process restart during an open position.
- **SC-006**: Forward test reports include statistical limitation
  warnings for small samples and explicitly state results do not
  authorize live trading.
- **SC-007**: The system stops new order submission within 1 second
  of duration expiry or approval revocation.

## Assumptions

- Phase 8 requires completion of Phases 2–7 and owner approval of
  backtest results meeting the Phase 7 acceptance criteria.
- The Demo account is a standard MT5 Demo with the approved broker.
  Demo conditions (spread, execution, margin) may differ from live.
- The EA order handler must be implemented and tested before Phase 8
  begins. The current EA is read-only (Constitution Principle III).
  Implementing the order handler requires separate explicit owner
  approval.
- "Statistically meaningful" sample size is an owner decision. The
  system reports sample size and warns when it is small, but does not
  define the threshold.
- The forward test runs on the approved WSL + Windows MT5 topology.
  No remote deployment is assumed.
- Swap costs are real (charged by the Demo broker) and recorded as
  actuals, not estimates.
