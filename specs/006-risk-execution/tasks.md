# Tasks: Phase 5 — Risk and Execution

**Input**: Design documents from `specs/006-risk-execution/`

**Prerequisites**: plan.md, spec.md, data-model.md, contracts/order-lifecycle.md, research.md, quickstart.md

**Note**: Phase 5 implements pre-trade risk validation, daily risk state machine, durable order
lifecycle, pair reservations, startup reconciliation, and PostgreSQL persistence. The EA is
read-only; broker execution is a design contract until an order handler is separately approved.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1–US7)
- Include exact file paths in descriptions

---

## Phase 1: Setup

**Purpose**: Order, risk, and execution type definitions shared across all stories

- [ ] T001 Create src/scalping_core/order_types.py defining: OrderState enum (DRAFT, PENDING_SUBMIT, SUBMITTING, SUBMITTED, FILLED, REJECTED, CANCELLED, UNKNOWN, OPERATOR_RESOLVED — blocking states: DRAFT/PENDING_SUBMIT/SUBMITTING/SUBMITTED/UNKNOWN; terminal states: FILLED/REJECTED/CANCELLED/OPERATOR_RESOLVED), OutcomeType enum (FILLED, REJECTED, CANCELLED, TIMEOUT, UNKNOWN), ReservationStatus enum (HELD, RELEASED), PositionStatus enum (OPEN, CLOSED, SETTLING), DailyRiskStateEnum enum (ACTIVE, PROFIT_LOCKED, LOSS_LOCKED, DRAINING, DISABLED), RiskEventType enum (ENTRY_REJECTED, LIMIT_TRIGGERED, LOCK_ACTIVATED, LOCK_RESET, OPERATOR_RESOLUTION, BARRIER_HELD, BARRIER_RELEASED, RECONCILIATION_START, RECONCILIATION_COMPLETE, FILL_PERSIST_FAILURE, ADMISSION_HALTED), BarrierStatus enum (HELD, RELEASED)
- [ ] T002 Add dataclasses to src/scalping_core/order_types.py: OrderIntent (intent_id: uuid PK, pair: str NOT NULL, account_id: str NOT NULL, direction: BUY/SELL NOT NULL, lot_size: Decimal fixed 0.01 positive NOT NULL, entry_price_ref: Decimal NOT NULL, stop_loss_price: Decimal NOT NULL, take_profit_price: Decimal NOT NULL, estimated_loss: Decimal NOT NULL, strategy_name: str NOT NULL, signal_id: uuid NOT NULL, state: OrderState NOT NULL, created_at: datetime tz NOT NULL, updated_at: datetime tz NOT NULL), OrderOutcome (outcome_id: uuid PK, intent_id: uuid FK NOT NULL UNIQUE, broker_ticket: str nullable, fill_price: Decimal nullable, fill_time: datetime nullable, outcome_type: OutcomeType NOT NULL, broker_error: str nullable, correlation_token: str nullable, recorded_at: datetime tz NOT NULL)
- [ ] T003 Add dataclasses to src/scalping_core/order_types.py: PairReservation (reservation_id: uuid PK, pair: str NOT NULL, account_id: str NOT NULL, intent_id: uuid FK NOT NULL, status: HELD/RELEASED NOT NULL, acquired_at: datetime NOT NULL, released_at: datetime nullable), Position (position_id: uuid PK, pair: str NOT NULL, account_id: str NOT NULL, intent_id: uuid FK NOT NULL, direction: BUY/SELL NOT NULL, lot_size: Decimal NOT NULL, entry_price: Decimal NOT NULL, stop_loss: Decimal NOT NULL, take_profit: Decimal NOT NULL, status: OPEN/CLOSED/SETTLING NOT NULL, entry_time: datetime NOT NULL, exit_price: Decimal nullable, exit_time: datetime nullable, realized_pnl: Decimal nullable, commission: Decimal nullable, swap: Decimal nullable — partial unique: at most one OPEN per pair per account)
- [ ] T004 Add dataclasses to src/scalping_core/order_types.py: DailyRiskState (risk_state_id: uuid PK, account_id: str NOT NULL, trading_day: date Asia/Amman boundary NOT NULL, state: DailyRiskStateEnum NOT NULL, realized_pnl: Decimal default 0 NOT NULL, floating_pnl: Decimal default 0 NOT NULL, commissions: Decimal default 0 NOT NULL, swaps: Decimal default 0 NOT NULL, net_pnl: Decimal NOT NULL, profit_limit: Decimal default +15.00 NOT NULL, loss_limit: Decimal default -5.00 NOT NULL, state_changed_at: datetime NOT NULL, locked_by: str nullable — unique: one per account per trading_day), RiskEvent (event_id: uuid PK, account_id: str NOT NULL, event_type: RiskEventType NOT NULL, detail: str NOT NULL, related_intent_id: uuid nullable, related_position_id: uuid nullable, operator_id: str nullable, created_at: datetime NOT NULL), ReconciliationBarrier (barrier_id: uuid PK, account_id: str NOT NULL, status: HELD/RELEASED NOT NULL, reason: str NOT NULL, held_at: datetime NOT NULL, released_at: datetime nullable, resolved_by: str nullable)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: PostgreSQL store abstraction and migration framework

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [ ] T005 Implement PostgreSQL store abstraction in src/scalping_core/durable_store.py: connection management for a dedicated disposable database, transaction support, parameterized query execution. Use psycopg or asyncpg. Application role must be least-privilege. Connection failure = fail-closed (no entry without durable state)
- [ ] T006 Implement migration runner in src/scalping_core/durable_store.py: apply versioned migrations from migrations/ directory (001–006) in order to a fresh database. Verify all tables, constraints, and indexes are created. Support upgrade path (e.g., 001–005 → 006). Migrations MUST only be applied to isolated disposable databases until separately approved for production (FR-016)
- [ ] T007 Write integration tests in tests/test_durable_store.py: test migration application to fresh database (all 001–006), test upgrade path, test constraint enforcement (FK, NOT NULL, CHECK, unique, partial unique), test connection failure handling (fail-closed)

**Checkpoint**: PostgreSQL store works with migrations applied and constraints enforced

---

## Phase 3: User Story 7 — Calculate Position Risk and P/L (Priority: P1) 🎯 MVP

**Goal**: Calculate estimated gross/net P/L before entry; validate against $0.50 ceiling

**Independent Test**: Calculate P/L for known parameters → verify matches manual calculation

- [ ] T008 [P] [US7] Implement P/L calculator in src/scalping_core/risk_gate.py: calculate estimated loss from: lot_size (fixed 0.01), stop_loss_distance (pips), pair pip value (from Phase 2 ContractSpecification), spread cost, commission estimate, slippage estimate, and account currency conversion. Document that $0.50 ceiling is an estimate — gaps/slippage/execution failures may cause realized loss to exceed it. Currency conversion interface exists but source/freshness deferred to §19#14
- [ ] T009 [P] [US7] Write unit tests in tests/test_risk_gate.py: test EURUSD BUY 0.01 lot with 5-pip stop (verify against manual calculation), test non-USD account currency conversion (interface), test commission and swap inclusion without double-counting, test that costs are additive (spread + commission + slippage)

**Checkpoint**: P/L calculations match manual verification for all tested scenarios

---

## Phase 4: User Story 1 — Validate Risk Before Entry (Priority: P1)

**Goal**: Reject entries exceeding $0.50 ceiling, below broker stop minimum, or failing margin

**Independent Test**: Submit entries with various risk profiles → verify correct accept/reject

- [ ] T010 [US1] Implement pre-trade risk validation in src/scalping_core/risk_gate.py: validate fixed lot 0.01 against broker volume_min/volume_max/volume_step (FR-001), validate estimated loss <= $0.50 ceiling (FR-002), validate stop distance >= broker min_stop_distance (FR-003), validate margin requirements, validate exposure limits. If stop cannot satisfy both broker minimum AND $0.50 ceiling → reject (never widen stop per FR-004). Return structured rejection reason on any failure
- [ ] T011 [US1] Write unit tests in tests/test_risk_gate.py: test entry approved (all checks pass), test rejection on $0.60 estimated loss, test rejection on stop below broker minimum, test rejection when stop meets broker min but exceeds $0.50 ceiling (stop not widened), test rejection on insufficient margin, test structured rejection reasons

**Checkpoint**: Risk validation rejects all entries exceeding safety limits

---

## Phase 5: User Story 2 — Enforce Daily Risk Limits (Priority: P1)

**Goal**: Track daily P/L, enforce +$15/-$5 limits, Asia/Amman reset, state machine

**Independent Test**: Simulate trading day with escalating P/L → verify limits trigger correctly

- [ ] T012 [US2] Implement daily risk state machine in src/scalping_core/daily_risk.py: states ACTIVE, PROFIT_LOCKED, LOSS_LOCKED, DRAINING, DISABLED per data-model.md transitions. Track daily net_pnl = realized_pnl + floating_pnl + commissions + swaps (FR-005). ACTIVE→PROFIT_LOCKED when net_pnl >= +15.00; ACTIVE→LOSS_LOCKED when net_pnl <= -5.00 (FR-005). DRAINING/DISABLED→ACTIVE requires authorized manual action only (survive rollover per FR-006). On limit trigger: block new entries, cancel pending entry orders, do NOT force-close open positions (FR-008/FR-020). Persist state transitions as RiskEvents
- [ ] T013 [US2] Implement daily reset with Asia/Amman timezone boundary in src/scalping_core/daily_risk.py: use zoneinfo.ZoneInfo("Asia/Amman") for explicit timezone-aware logic (FR-007). PROFIT_LOCKED and LOSS_LOCKED reset to ACTIVE at boundary. DRAINING and DISABLED do NOT reset. Create new DailyRiskState record for the new trading day
- [ ] T014 [US2] Write unit tests in tests/test_daily_risk.py: test ACTIVE→PROFIT_LOCKED at +$15 threshold, test ACTIVE→LOSS_LOCKED at -$5 threshold, test daily reset at Asia/Amman boundary (PROFIT_LOCKED→ACTIVE, LOSS_LOCKED→ACTIVE), test DRAINING survives rollover, test DISABLED survives rollover, test open positions NOT force-closed on lock, test manual reset is auditable, test P/L calculation includes commissions and swaps

**Checkpoint**: Daily limits trigger correctly; state machine transitions are sound

---

## Phase 6: User Story 4 — Enforce Pair Reservation and Duplicate Prevention (Priority: P1)

**Goal**: Max one active position per pair; durable reservation with concurrency safety

**Independent Test**: Attempt concurrent entries on same pair → only one succeeds

- [ ] T015 [US4] Implement pair reservation in src/scalping_core/pair_reservation.py: acquire durable HELD reservation before entry (FR-009/FR-010). Enforce at most one HELD reservation per pair per account via database unique constraint. Reject second entry with "pair reserved." Release reservation on terminal order states (FILLED after position created, REJECTED, CANCELLED, OPERATOR_RESOLVED). Serialize concurrent access via database row-level lock (FR-021)
- [ ] T016 [US4] Write unit tests in tests/test_admission_protocol.py: test reservation acquired before submission, test second entry rejected on reserved pair, test reservation released on rejection, test reservation released on position close/settlement, test reservation HELD on UNKNOWN outcome, test concurrent reservation attempts (only one succeeds per SC-006)

**Checkpoint**: Pair reservations prevent duplicate entries with zero false admissions

---

## Phase 7: User Story 3 — Manage Order Lifecycle Durably (Priority: P1)

**Goal**: Durable order state machine; persist before broker; handle ambiguous outcomes

**Independent Test**: Simulate all broker outcomes → verify state transitions and reservation behavior

- [ ] T017 [US3] Implement order lifecycle in src/scalping_core/execution_engine.py: follow entry admission sequence from contracts/order-lifecycle.md steps 1–14. Persist OrderIntent (DRAFT) before broker contact (FR-009). Transition DRAFT→PENDING_SUBMIT→SUBMITTING→SUBMITTED. Record OrderOutcome on broker response. On FILLED: create Position atomically, release reservation. On REJECTED/CANCELLED: release reservation. On TIMEOUT/DISCONNECT: transition to UNKNOWN, keep reservation HELD, do NOT resubmit (FR-011). State machine enforces valid transitions only — no DRAFT→FILLED shortcut (FR-017)
- [ ] T018 [US3] Implement ambiguous outcome handling in src/scalping_core/execution_engine.py: UNKNOWN state keeps pair reserved and reconciliation barrier potentially activated. Never auto-clear SUBMITTING on process death/timeout/"not found" (FR-013). Operator resolution creates auditable RiskEvent with operator_id and transitions to OPERATOR_RESOLVED (FR-018). A confirmed fill that fails to persist halts account-wide admission (FR-014)
- [ ] T019 [US3] Write unit tests in tests/test_execution_engine.py: test full lifecycle (DRAFT→...→FILLED→position created), test rejection path (→REJECTED→reservation released), test timeout path (→UNKNOWN→reservation held, no resubmit), test state machine rejects invalid transitions (SC-008), test intent persisted before broker call (SC-001), test operator resolution is auditable, test fill-persist-failure halts admission

**Checkpoint**: Order lifecycle handles all broker outcomes correctly; ambiguous states are safe

---

## Phase 8: User Story 5 — Reconcile State on Startup (Priority: P1)

**Goal**: Block entries until startup reconciliation resolves all dirty state

**Independent Test**: Simulate startup with dirty state → verify barrier blocks until resolved

- [ ] T020 [US5] Implement startup reconciliation in src/scalping_core/reconciliation.py: on startup, scan for non-terminal OrderIntents (DRAFT, PENDING_SUBMIT, SUBMITTING, SUBMITTED, UNKNOWN per contracts/order-lifecycle.md). If any found: hold ReconciliationBarrier account-wide, block all entries (FR-012). For SUBMITTING: NEVER auto-clear — requires authoritative evidence or operator (FR-013). For confirmed fills that failed to persist: halt account-wide admission (FR-014). Release barrier only when all non-terminal intents resolved. Log RECONCILIATION_START and RECONCILIATION_COMPLETE as RiskEvents
- [ ] T021 [US5] Write unit tests in tests/test_admission_protocol.py: test barrier held on in-flight SUBMITTING order (SC-007), test barrier released on clean state, test barrier blocks all entries during reconciliation, test SUBMITTING not auto-cleared on restart, test fill-persist-failure halts admission, test barrier survives restarts (durable)

**Checkpoint**: Startup reconciliation correctly blocks and resolves all dirty states

---

## Phase 9: User Story 6 — Persist Order and Risk State Durably (Priority: P1)

**Goal**: PostgreSQL persistence with constraints; versioned migrations

**Independent Test**: Create/persist entities → verify constraints → recover after crash

- [ ] T022 [US6] Implement entity persistence in src/scalping_core/durable_store.py: CRUD operations for OrderIntent, OrderOutcome, PairReservation, Position, DailyRiskState, RiskEvent, ReconciliationBarrier. Enforce all database constraints from data-model.md: FK (pair→CanonicalSymbol, intent→OrderIntent, etc.), NOT NULL on all required fields, CHECK (lot_size positive, estimated_loss positive), unique (one DailyRiskState per account/day, one HELD reservation per pair/account), partial unique (at most one non-terminal OrderIntent per pair/account, at most one OPEN Position per pair/account per FR-015)
- [ ] T023 [US6] Write integration tests in tests/test_durable_store.py: test OrderIntent survives restart, test constraint rejects second unresolved entry for same pair (SC-009), test constraint rejects second OPEN position for same pair, test FK enforcement, test NOT NULL enforcement, test migration upgrade path (001–005 → 006 without data loss)

**Checkpoint**: All entities persist durably; constraints reject invalid data

---

## Phase 10: Polish & Cross-Cutting Concerns

**Purpose**: Full pipeline integration and end-to-end validation

- [ ] T024 Wire the full entry admission pipeline in src/scalping_core/execution_engine.py: signal recommendation → fresh quote → spread gate (Phase 3) → regime check (Phase 4) → daily risk check → reservation check → barrier check → risk calculation → risk validation → persist intent → acquire reservation → submit (design contract). Follow contracts/order-lifecycle.md steps 1–14 exactly. Any failure at steps 1–11 rejects without creating intent
- [ ] T025 Write integration tests in tests/test_execution_engine.py: test full pipeline happy path (signal → risk → intent → reservation → submission → fill → position), test pipeline with daily limit locked (blocked), test pipeline with pair reserved (blocked), test pipeline with barrier held (blocked), test pipeline with risk failure (rejected before intent)
- [ ] T026 Run quickstart.md validation scenarios end-to-end and record PASS/FAIL evidence

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — T001–T004 can start immediately
- **Foundational (Phase 2)**: Depends on Setup — T005–T007 need order_types
- **User Stories (Phases 3–9)**: All depend on Foundational (PostgreSQL store)
  - US7 can start first (P/L calc, no DB dependency for unit tests)
  - US1 depends on US7 (risk validation needs P/L calculator)
  - US2 independent of US1 (daily risk is separate concern)
  - US4 independent (pair reservation is separate concern)
  - US3 depends on US4 (order lifecycle uses reservations)
  - US5 depends on US3 (reconciliation scans orders)
  - US6 depends on all entities being defined (persistence layer)
- **Polish (Phase 10)**: Depends on all user stories

### User Story Dependencies

- **US7 (P1)**: No dependencies — P/L calculation is standalone
- **US1 (P1)**: Depends on US7 (risk validation calls P/L calculator)
- **US2 (P1)**: No dependencies on other stories (daily risk is independent)
- **US4 (P1)**: No dependencies on other stories (reservations are independent)
- **US3 (P1)**: Depends on US4 (order lifecycle needs reservations)
- **US5 (P1)**: Depends on US3 (reconciliation scans order states)
- **US6 (P1)**: Can start after Foundational (persistence is cross-cutting)

### Parallel Opportunities

- US7 and US2 and US4 and US6 can all run in parallel (different files, independent concerns)
- T008/T009 are [P] within US7
- After US7: US1 can proceed
- After US4: US3 can proceed
- After US3: US5 can proceed

---

## Parallel Example: Independent Concerns

```bash
# After Foundational, start four independent tracks:
# US7: T008-T009 in risk_gate.py (P/L calculation)
# US2: T012-T014 in daily_risk.py (daily limits)
# US4: T015-T016 in pair_reservation.py (reservations)
# US6: T022-T023 in durable_store.py (persistence)
```

---

## Implementation Strategy

### MVP First (User Story 7 → User Story 1)

1. Complete T001–T004 (Setup: all types)
2. Complete T005–T007 (Foundational: PostgreSQL store + migrations)
3. Complete T008–T009 (US7: P/L calculator)
4. Complete T010–T011 (US1: risk validation)
5. **STOP and VALIDATE**: Entries correctly accepted/rejected by risk limits
6. Proceed to US2–US6

### Incremental Delivery

1. Setup + Foundational → types and PostgreSQL ready
2. US7 (T008–T009) → P/L calculations work
3. US1 (T010–T011) → risk validation enforces limits
4. US2 + US4 + US6 (parallel: T012–T016, T022–T023) → daily risk + reservations + persistence
5. US3 (T017–T019) → order lifecycle works
6. US5 (T020–T021) → startup reconciliation works
7. Polish (T024–T026) → full pipeline wired, integration tested

---

## Notes

- EA is read-only — broker execution is a design contract until order handler is approved
- Fixed lot 0.01 for pilot; variable sizing out of scope
- $0.50/$15/$5 are master plan values; configurable via dashboard in Phase 6
- Stop is never widened to fit broker constraints (FR-004)
- Ambiguous outcomes never auto-resubmit (FR-011)
- Open positions never force-closed on limits (FR-020)
- Currency conversion source deferred to §19#14; partial fills deferred to §19#15
- Close-management permissions deferred to §19#12; exit rules deferred to §19#1,6,7
- Migrations applied only to disposable databases until separately approved (FR-016)
- All state transitions logged as RiskEvents for audit trail
