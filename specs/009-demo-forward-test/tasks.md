# Tasks: Phase 8 — Demo Forward Test

**Input**: Design documents from `specs/009-demo-forward-test/`

**Prerequisites**: plan.md, spec.md, data-model.md, contracts/demo-scope.md, research.md, quickstart.md

**Note**: Phase 8 is the first broker-mutating phase. It enables Demo order submission through the
existing Phase 5 execution pipeline. Constitution Principle III requires explicit owner approval
before EA order handler implementation and activation. All Phase 5 safety mechanisms remain active.
Every event is recorded. Results do NOT authorize live trading.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1–US5)
- Include exact file paths in descriptions

---

## Phase 1: Setup

**Purpose**: Demo subpackage structure and database migration

- [ ] T001 Create the demo subpackage directory at src/scalping/demo/ with __init__.py
- [ ] T002 Create migration 009 in migrations/009_demo_forward_test.sql adding tables: demo_scope_approval (approval_id uuid PK, account_id string FK NOT NULL, account_type string NOT NULL CHECK = 'DEMO', approved_pair string FK NOT NULL, approved_lot_size decimal NOT NULL must match 0.01, start_time timestamp NOT NULL, end_time timestamp NOT NULL CHECK end_time > start_time, stop_conditions string JSON NOT NULL, monitoring_requirements string JSON NOT NULL, status enum ACTIVE/EXPIRED/REVOKED NOT NULL, approved_by string NOT NULL, approved_at timestamp NOT NULL, revoked_at timestamp nullable, revocation_reason string nullable — at most one ACTIVE approval at a time via partial unique), forward_test_session (session_id uuid PK, approval_id uuid FK NOT NULL, started_at timestamp NOT NULL, ended_at timestamp nullable, end_reason string nullable "duration_expired"/"owner_revoked"/"emergency_stop"/"manual_stop", total_signals integer NOT NULL default 0, total_entries_attempted integer NOT NULL default 0, total_entries_rejected integer NOT NULL default 0, total_fills integer NOT NULL default 0, total_rejections integer NOT NULL default 0, net_pnl decimal nullable, total_costs decimal nullable), forward_test_event (event_id uuid PK, session_id uuid FK NOT NULL, event_type enum SIGNAL_GENERATED/SIGNAL_REJECTED/ENTRY_APPROVED/ENTRY_REJECTED/ORDER_SUBMITTED/ORDER_FILLED/ORDER_REJECTED/ORDER_TIMEOUT/FILL_DISCREPANCY/COST_RECORDED/SPREAD_AT_DECISION/LATENCY_RECORDED/DURATION_EXPIRED/APPROVAL_REVOKED NOT NULL, timestamp timestamp NOT NULL, pair string FK NOT NULL, detail string JSON NOT NULL, related_intent_id uuid FK nullable, related_signal_id uuid nullable), execution_discrepancy (discrepancy_id uuid PK, session_id uuid FK NOT NULL, intent_id uuid FK NOT NULL, expected_price decimal NOT NULL, actual_price decimal NOT NULL, slippage_pips decimal NOT NULL, submission_time timestamp NOT NULL, fill_time timestamp NOT NULL, latency_ms integer NOT NULL, direction enum BUY/SELL NOT NULL), forward_test_report (report_id uuid PK, session_id uuid FK NOT NULL UNIQUE, sample_size integer NOT NULL, sample_sufficient boolean NOT NULL, net_pnl decimal NOT NULL, gross_pnl decimal NOT NULL, total_spread_cost decimal NOT NULL, total_commission decimal NOT NULL, total_swap decimal NOT NULL, avg_slippage_pips decimal NOT NULL, max_drawdown decimal NOT NULL, win_rate decimal NOT NULL, avg_trade_duration interval NOT NULL, statistical_warnings string JSON array NOT NULL, generated_at timestamp NOT NULL)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Demo scope gate and evidence recording infrastructure that all stories depend on

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [ ] T003 Implement Demo scope gate in src/scalping/demo/scope.py: on startup and before every order, verify all gates per contracts/demo-scope.md — DemoScopeApproval exists with status ACTIVE, connected account matches approved account_id, account_type verified as Demo (with broker, not self-reported), current time within approved duration (start_time ≤ now ≤ end_time), approved_pair matches order pair, approved_lot_size matches order lot. Any gate failure → block order with structured reason, release Phase 5 reservation. Return "no Demo approval" when no ACTIVE approval exists (FR-001, SC-001)
- [ ] T004 Implement evidence recording in src/scalping/demo/evidence.py: record ForwardTestEvent for every pipeline step per contracts/demo-scope.md event table — SIGNAL_GENERATED, SIGNAL_REJECTED, ENTRY_APPROVED, ENTRY_REJECTED (with reason code), ORDER_SUBMITTED, ORDER_FILLED, ORDER_REJECTED, ORDER_TIMEOUT, FILL_DISCREPANCY, COST_RECORDED, SPREAD_AT_DECISION, LATENCY_RECORDED. No silent drops (FR-009, FR-010): if DB write fails, log the failure and record it when DB recovers. Each event includes session_id, timestamp, pair, JSON detail, optional related_intent_id and related_signal_id
- [ ] T005 [P] Implement duration expiry and revocation handling in src/scalping/demo/scope.py: when current time > end_time → set status to EXPIRED, block new entries (equivalent to DRAINING), record DURATION_EXPIRED event, set ForwardTestSession.ended_at and end_reason="duration_expired". On owner revocation → set status to REVOKED, block new entries immediately, record APPROVAL_REVOKED event, set end_reason="owner_revoked". Open positions continue managed (SL/TP active, not force-closed). Stop new submissions within 1 second of expiry/revocation (SC-007, FR-013)

**Checkpoint**: Demo scope gate and evidence recording operational — order submission can proceed

---

## Phase 3: User Story 1 — Define Demo Test Scope (Priority: P0) 🎯 MVP

**Goal**: Owner defines and approves Demo scope before any order submission; no orders without approval

**Independent Test**: Present scope document to owner → verify approval recorded → attempt order without approval → verify refusal

- [ ] T006 [US1] Implement Demo scope approval management in src/scalping/demo/scope.py: create DemoScopeApproval record from owner input — account_id (FK, NOT NULL), account_type (must be "DEMO", CHECK), approved_pair (FK, NOT NULL), approved_lot_size (must be 0.01, NOT NULL), start_time/end_time (NOT NULL, end > start), stop_conditions (JSON, NOT NULL), monitoring_requirements (JSON, NOT NULL), approved_by (NOT NULL), approved_at (NOT NULL). Enforce at most one ACTIVE approval at a time (partial unique constraint). Status starts as ACTIVE. Refuse if account_type is not 'DEMO'
- [ ] T007 [US1] Write unit tests in tests/test_demo_scope.py: test system refuses order submission without ACTIVE approval (SC-001, FR-001), test approval recorded with all required fields, test order for non-approved pair refused, test order after duration expires refused, test at most one ACTIVE approval enforced, test account_type CHECK rejects non-DEMO

**Checkpoint**: Demo scope approval gate enforced — no orders without explicit owner authorization

---

## Phase 4: User Story 2 — Execute Demo Orders (Priority: P1)

**Goal**: Submit orders to Demo through existing Phase 5 pipeline with all safety mechanisms active

**Independent Test**: Submit single order → verify full lifecycle: intent → reservation → submission → fill/reject → position or release

- [ ] T008 [US2] Implement EA order handler in mql5/DemoOrderHandler.mq5: NEW MQL5 file (NOT a modification of ReadOnlyConnector.mq5) that handles order submission for Demo account only (FR-004). Receive order request via TCP from Python backend, submit to Demo broker via MT5 trade functions, return fill/reject/timeout result. Verify connected account is Demo before processing. This file requires separate owner approval for implementation per Constitution Principle III
- [ ] T009 [US2] Integrate Demo scope gate with Phase 5 execution pipeline in src/scalping/demo/scope.py: insert Demo scope gate check after Phase 5 admission sequence (steps 1–14) and before broker adapter call per contracts/demo-scope.md execution contract. On gate pass → route to EA order handler → record outcome via Phase 5. On gate fail → block order, release Phase 5 reservation, record ENTRY_REJECTED event with structured reason. Use existing Phase 5 execution pipeline unchanged (FR-003)
- [ ] T010 [US2] Implement execution discrepancy recording in src/scalping/demo/evidence.py: on each fill, compare expected_price (reference at submission) vs actual_price (broker fill). Record ExecutionDiscrepancy: slippage_pips (difference in pips), submission_time, fill_time, latency_ms (fill_time - submission_time), direction (BUY/SELL). Record FILL_DISCREPANCY event when expected ≠ actual. Record LATENCY_RECORDED event for every fill
- [ ] T011 [US2] Write unit tests in tests/test_demo_scope.py: test order follows Phase 5 admission sequence then Demo gate, test broker fill creates position atomically (acceptance scenario US2-2), test broker rejection releases reservation (US2-3), test timeout follows Phase 5 UNKNOWN protocol — reservation held, no auto-resubmit (US2-4), test only approved Demo account receives orders (FR-004)

**Checkpoint**: Demo order lifecycle functional through Phase 5 pipeline

---

## Phase 5: User Story 3 — Verify Safety Mechanisms Under Real Conditions (Priority: P1)

**Goal**: Owner verifies all protective mechanisms work with real broker: reconciliation, SL/TP, duplicates, daily locks, emergency stop

**Independent Test**: Kill backend during open position → restart → verify reconciliation barrier activates and new entries blocked

- [ ] T012 [US3] Document safety verification test plan in specs/009-demo-forward-test/quickstart.md (extend existing): define manual test scenarios for each safety mechanism — (1) startup reconciliation after process kill with open position (FR-005, SC-005), (2) SL/TP placement verified against broker terminal (FR-006, SC-004), (3) duplicate protection via pair reservation when first order in-flight (FR-007), (4) daily loss limit triggers LOSS_LOCKED (FR-008), (5) emergency stop from dashboard triggers DRAINING (FR-014), (6) MT5 disconnect/reconnect recovery (FR-015). Each scenario includes: trigger action, expected system behavior, evidence to capture
- [ ] T013 [US3] Implement safety verification event recording in src/scalping/demo/evidence.py: record events specific to safety verification — reconciliation barrier activation, SL/TP placement confirmation, pair reservation rejection, daily limit state transitions, emergency stop activation, disconnect/reconnect events. Each event links to ForwardTestSession for the active test
- [ ] T014 [US3] Write unit tests in tests/test_demo_scope.py: test reconciliation barrier blocks new entries after restart (SC-005), test pair reservation rejects second signal for same pair (FR-007), test daily P/L reaching loss limit transitions to LOSS_LOCKED (FR-008), test emergency stop transitions to DRAINING (FR-014), test margin exhaustion blocks entries without switching accounts

**Checkpoint**: Safety mechanisms verified under real broker conditions with evidence

---

## Phase 6: User Story 4 — Record Every Event (Priority: P1)

**Goal**: Complete evidence log — every signal, decision, broker interaction, and cost recorded; no silent drops

**Independent Test**: Run test session → verify event log contains entry for every signal, every decision, every broker interaction, every cost

- [ ] T015 [US4] Implement comprehensive event recording hooks in src/scalping/demo/evidence.py: hook into existing Phase 3–5 pipeline to capture all events — SIGNAL_GENERATED (every signal regardless of outcome), SIGNAL_REJECTED (with reason from Phase 4), ENTRY_APPROVED/ENTRY_REJECTED (with specific reason: spread gate, risk limit, pair reserved, etc.), ORDER_SUBMITTED, ORDER_FILLED, ORDER_REJECTED, ORDER_TIMEOUT, COST_RECORDED (spread, commission, swap, slippage per trade), SPREAD_AT_DECISION (spread snapshot when entry decision made). Update ForwardTestSession counters: total_signals, total_entries_attempted, total_entries_rejected, total_fills, total_rejections (FR-009, SC-002)
- [ ] T016 [US4] Write unit tests in tests/test_demo_evidence.py: test every signal recorded regardless of outcome (FR-009), test rejected entries include specific reason code (US4-2), test completed trades record all cost components (US4-3), test fill discrepancy recorded with both values (US4-4), test no event silently dropped (FR-010), test session counters updated correctly, test DB write failure logged and recovered

**Checkpoint**: Evidence log captures 100% of events with no silent drops

---

## Phase 7: User Story 5 — Prevent False Expectancy Claims (Priority: P1)

**Goal**: Honest reporting with statistical limitations; no positive expectancy from small samples; no live trading authorization

**Independent Test**: Generate report from 5-trade sample → verify statistical limitation warning present

- [ ] T017 [US5] Implement forward test report generation in src/scalping/demo/report.py: generate ForwardTestReport from ForwardTestSession data — sample_size (completed trades), sample_sufficient (owner-defined threshold), net_pnl (after all costs), gross_pnl, cost breakdown (total_spread_cost, total_commission, total_swap), avg_slippage_pips (from ExecutionDiscrepancy records), max_drawdown, win_rate, avg_trade_duration. Mandatory statistical_warnings JSON array: always include "These results do not authorize live trading" (FR-012). If sample_sufficient=false, add "Insufficient sample size for statistical inference" (FR-011). Never claim "positive expectancy" without documented statistical test. Never claim "profitable strategy" from small sample (SC-006)
- [ ] T018 [US5] Write unit tests in tests/test_demo_report.py: test report always includes "do not authorize live trading" disclaimer (FR-012, SC-006), test insufficient sample warning present for small samples (FR-011), test no "positive expectancy" claim without statistical evidence, test all cost components in breakdown, test avg_slippage_pips computed from ExecutionDiscrepancy, test empty statistical_warnings array never occurs (mandatory disclaimer always present)

**Checkpoint**: Reports are honest with mandatory limitations and disclaimers

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: EA integration, end-to-end verification, edge cases

- [ ] T019 Extend TCP protocol in src/scalping/tcp_broker_adapter.py to route order requests to DemoOrderHandler.mq5 when Demo scope gate is active. Route read-only requests to ReadOnlyConnector.mq5 as before. Verify account is Demo with broker (not self-reported) before routing any order. Ensure no order path exists to Live accounts
- [ ] T020 Implement edge case handling in src/scalping/demo/scope.py: margin exhaustion → report and block entries, no account switching. Duration expiry with open position → block new entries, manage open position (SL/TP remain active, no force-close). Approval revocation mid-test → block new entries immediately, manage open positions, transition to DRAINING-equivalent state
- [ ] T021 Write integration tests in tests/test_demo_scope.py: test full end-to-end order lifecycle on Demo (signal → gate → submission → fill → evidence → report), test duration expiry blocks new entries but manages open positions, test approval revocation blocks entries immediately, test Demo server unavailability follows disconnect/reconnect protocol
- [ ] T022 Run quickstart.md validation scenarios end-to-end and record PASS/FAIL evidence. Note: safety verification scenarios (T012) require owner execution against real MT5 Demo terminal

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — T001/T002 can start immediately
- **Foundational (Phase 2)**: Depends on Setup — T003–T005 need package structure and tables
- **US1 (Phase 3)**: Depends on Foundational (Demo scope gate)
- **US2 (Phase 4)**: Depends on US1 (needs approved Demo scope before order submission)
- **US3 (Phase 5)**: Depends on US2 (safety verification needs working order submission)
- **US4 (Phase 6)**: Depends on Foundational (evidence recording hooks into pipeline)
- **US5 (Phase 7)**: Depends on US4 (report generated from evidence data)
- **Polish (Phase 8)**: Depends on all user stories

### User Story Dependencies

- **US1 (P0)**: No dependencies on other stories — approval gate is foundational
- **US2 (P1)**: Depends on US1 (needs approved scope to submit orders)
- **US3 (P1)**: Depends on US2 (safety verification needs real orders)
- **US4 (P1)**: Depends on Foundational only (evidence hooks are independent)
- **US5 (P1)**: Depends on US4 (report needs evidence data)

### Parallel Opportunities

- US4 (evidence recording) can run in parallel with US2 (order execution) — different files
- T005 (duration/revocation) can run in parallel with T003/T004
- T012 (safety test plan) can be written in parallel with US2 implementation

---

## Parallel Example: Evidence + Order Execution

```bash
# After Foundational + US1, start in parallel:
# US2: T008-T011 (order execution — scope.py + DemoOrderHandler.mq5)
# US4: T015-T016 (evidence recording — evidence.py, different file)
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete T001–T002 (Setup: package + migration)
2. Complete T003–T005 (Foundational: scope gate + evidence + duration handling)
3. Complete T006–T007 (US1: Demo scope approval management)
4. **STOP and VALIDATE**: Owner can define scope; system refuses orders without approval
5. Proceed to US2–US5

### Incremental Delivery

1. Setup + Foundational → scope gate, evidence recording, duration handling ready
2. US1 (T006–T007) → Demo scope approval gate enforced
3. US2 + US4 (parallel: T008–T011, T015–T016) → order execution + evidence recording
4. US3 (T012–T014) → safety verification under real conditions
5. US5 (T017–T018) → honest reporting with limitations
6. Polish (T019–T022) → EA integration, edge cases, end-to-end validation

---

## Notes

- This is the first broker-mutating phase — Constitution Principle III requires explicit owner approval
- EA order handler (DemoOrderHandler.mq5) is a NEW file, not a modification of ReadOnlyConnector.mq5
- EA order handler implementation requires separate owner approval before any code is written
- All Phase 5 safety mechanisms remain active: durable intent, pair reservation, reconciliation, daily limits
- Demo account type verified with broker (not self-reported) — no order path to Live accounts
- Forward test results do NOT authorize live trading — separate explicit authorization required
- "Statistically meaningful" sample size is an owner decision — system warns, doesn't threshold
- Swap costs are real (charged by Demo broker), recorded as actuals not estimates
- Evidence recording has no silent drops — DB write failures logged and recovered
