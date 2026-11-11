# Tasks: Phase 2 — Broker Connectivity

**Input**: Design documents from `specs/003-broker-connectivity/`

**Prerequisites**: plan.md, spec.md, data-model.md, contracts/tcp-protocol.md, research.md, quickstart.md

**Note**: Phase 2 is the first implementation phase. It produces a read-only broker
connectivity layer: TCP connection, account discovery, symbol registry, contract specs,
and fail-closed behavior. The connector remains read-only per constitution Principle III.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1–US5)
- Include exact file paths in descriptions

---

## Phase 1: Setup

**Purpose**: Project structure and shared type definitions

- [X] T001 Create the broker types module at src/scalping_core/broker_types.py defining: BrokerConnectionState enum (CONNECTED, DISCONNECTED, RECONNECTING), Account dataclass (account_number: int, broker_name: str, balance: Decimal, equity: Decimal, margin: Decimal, currency: str — currency is 3-letter code), CanonicalSymbol dataclass (name: str — unique, is_forex: bool — must be True for Forex), BrokerSymbol dataclass (broker_name: str, trading_permitted: bool, account_number: int), SymbolMapping dataclass (canonical_symbol: CanonicalSymbol, broker_symbol: BrokerSymbol, confirmed_by_owner: bool — default False), ContractSpecification dataclass (all 15 fields from data-model.md: digits as non-negative int, point/tick_size/tick_value/contract_size/volume_min/volume_max/volume_step as positive Decimal, min_stop_distance as non-negative int, trading_permissions as str, margin_requirement as positive Decimal, commission as Decimal, swap_long as Decimal, swap_short as Decimal)
- [X] T002 Create the broker adapter abstraction at src/scalping_core/broker_adapter.py defining the abstract interface: connect(), disconnect(), get_account_info() → Account, discover_symbols() → list[BrokerSymbol], get_contract_spec(symbol: str) → ContractSpecification, get_connection_state() → BrokerConnectionState. Interface must NOT include order submission methods (read-only per FR-011)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: TCP framing and message parsing that all stories depend on

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T003 Implement length-prefixed JSON message framing in src/scalping_core/tcp_broker_adapter.py: 4-byte big-endian length header + UTF-8 JSON payload (per contracts/tcp-protocol.md). Include send_message(sock, payload: dict) and recv_message(sock) → dict functions. Handle partial reads and broken pipes gracefully
- [X] T004 Implement message type dispatching in src/scalping_core/tcp_broker_adapter.py: parse incoming message "type" field, route to handlers for "heartbeat", "account_info", "symbols", "contract_spec". Reject malformed messages (invalid JSON, missing "type", unknown type) by logging and discarding — do NOT close connection on single malformed message (per tcp-protocol.md Error Handling)

**Checkpoint**: TCP framing and message dispatch work — ready for user story implementation

---

## Phase 3: User Story 1 — Connect to a Demo Account (Priority: P1) 🎯 MVP

**Goal**: TCP connection to MT5, account info retrieval, disconnect detection, auto-reconnect

**Independent Test**: Start backend + EA on Demo account → backend receives account info within 5s. Stop EA → backend detects disconnect within 10s. Restart EA → reconnection succeeds automatically

- [X] T005 [US1] Implement TCP server listener in src/scalping_core/tcp_broker_adapter.py: bind to 127.0.0.1 (localhost only per FR-009/constitution), accept one EA connection, transition state DISCONNECTED → RECONNECTING → CONNECTED on successful ACCOUNT_INFO receipt
- [X] T006 [US1] Implement heartbeat monitoring in src/scalping_core/tcp_broker_adapter.py: track last_heartbeat timestamp from "heartbeat" messages, detect disconnect when no heartbeat received within 10 seconds (SC-002), transition to DISCONNECTED on timeout or socket error
- [X] T007 [US1] Implement auto-reconnection in src/scalping_core/tcp_broker_adapter.py: when connection is lost, return to listener state and accept new EA connection without manual intervention (FR-003). On reconnect, require fresh ACCOUNT_INFO before transitioning to CONNECTED
- [X] T008 [US1] Implement ACCOUNT_INFO handler in src/scalping_core/tcp_broker_adapter.py: parse account_number (int), broker_name (str, non-empty), balance (Decimal, positive), equity (Decimal), margin (Decimal, non-negative), currency (str, 3-letter code). Reject message if any required field is missing or invalid type
- [X] T009 [US1] Write unit tests in tests/test_tcp_broker_adapter.py: test framing (length-prefixed send/recv), heartbeat timeout detection, ACCOUNT_INFO parsing (valid and malformed), connection state transitions (DISCONNECTED→RECONNECTING→CONNECTED→DISCONNECTED), malformed message rejection

**Checkpoint**: Backend connects to EA, receives account info, detects disconnection, and auto-reconnects

---

## Phase 4: User Story 2 — Discover Available Symbols (Priority: P1)

**Goal**: Request and receive the complete list of broker symbols with trading permissions

**Independent Test**: Connect to Demo → request symbols → receive complete list with trading_permitted flags

- [X] T010 [P] [US2] Implement REQUEST_SYMBOLS sender in src/scalping_core/tcp_broker_adapter.py: send {"type": "request_symbols"} to EA and handle the "symbols" response. Parse each symbol entry: name (str), trading_permitted (bool). Store as list[BrokerSymbol] associated with the connected account_number
- [X] T011 [US2] Implement symbol unavailability handling in src/scalping_core/tcp_broker_adapter.py: when a queried symbol is not in the discovered list, return a clear "symbol unavailable" result — never guess or use a default (FR-004, SC-003)
- [X] T012 [US2] Write unit tests in tests/test_broker_adapter.py: test symbol discovery parsing (valid list, empty list, malformed entry), symbol lookup for existing and non-existing symbols

**Checkpoint**: Backend discovers all broker symbols on the connected account

---

## Phase 5: User Story 3 — Map Broker Symbols to Canonical Names (Priority: P1)

**Goal**: Canonical symbol registry with broker-specific alias mapping and owner confirmation

**Independent Test**: Discover symbols → system proposes canonical mappings → owner modifies a mapping → mapping persists in memory

- [X] T013 [US3] Implement CanonicalSymbol registry in src/scalping_core/broker_adapter.py: maintain a registry of known Forex canonical symbols (e.g., EURUSD, GBPUSD). Validate that is_forex is True. Provide lookup by canonical name
- [X] T014 [US3] Implement symbol mapping logic in src/scalping_core/broker_adapter.py: given discovered BrokerSymbols, propose SymbolMapping entries by matching broker names to canonical names (exact match or common suffix stripping like "EURUSD_" → "EURUSD"). Enforce uniqueness: one broker symbol per canonical symbol per account
- [X] T015 [US3] Implement owner mapping modification in src/scalping_core/broker_adapter.py: allow update_mapping(canonical_name, broker_name) to change or confirm a mapping. Set confirmed_by_owner to True. Report unmapped canonical symbols as "unmapped" — never guess (FR-006, SC-006)
- [X] T016 [US3] Write unit tests in tests/test_broker_adapter.py: test canonical Forex pair validation, alias inference (suffix stripping), mapping uniqueness constraint, owner modification persistence, unmapped symbol reporting

**Checkpoint**: Canonical symbol registry works with broker alias mapping and owner modifications

---

## Phase 6: User Story 4 — Retrieve Contract Specifications (Priority: P2)

**Goal**: Retrieve and validate all 15 contract fields for each mapped symbol

**Independent Test**: Map a symbol → request contract spec → all 15 fields populated from broker data → no defaults used

- [X] T017 [US4] Implement REQUEST_CONTRACT_SPEC sender and CONTRACT_SPEC handler in src/scalping_core/tcp_broker_adapter.py: send {"type": "request_contract_spec", "symbol": "<broker_name>"} and parse the response. Validate all 15 fields (digits: non-negative int, point: positive Decimal, tick_size: positive Decimal, tick_value: positive Decimal, contract_size: positive Decimal, volume_min: positive Decimal, volume_max: positive Decimal, volume_step: positive Decimal, min_stop_distance: non-negative int, trading_permissions: str, margin_requirement: positive Decimal, commission: Decimal, swap_long: Decimal, swap_short: Decimal)
- [X] T018 [US4] Implement contract eligibility check in src/scalping_core/broker_adapter.py: if any of the 15 required fields is missing, null, or fails its type/constraint validation, mark the symbol as ineligible for trading (FR-008). Log which field(s) failed. Never substitute default values
- [X] T019 [US4] Write unit tests in tests/test_broker_adapter.py: test contract spec parsing (all fields valid, missing field, invalid type), eligibility marking, refresh detection (changed value)

**Checkpoint**: Contract specifications retrieved and validated for mapped symbols; ineligible symbols are flagged

---

## Phase 7: User Story 5 — Fail-Closed on Connection Loss (Priority: P2)

**Goal**: Block all broker-dependent operations when disconnected; re-enable only after fresh data confirmed

**Independent Test**: Disconnect EA → all broker operations return "broker unavailable" → reconnect → operations succeed only after fresh ACCOUNT_INFO received

- [X] T020 [US5] Implement fail-closed guard in src/scalping_core/tcp_broker_adapter.py: when connection state is DISCONNECTED or RECONNECTING, all broker-dependent methods (get_account_info, discover_symbols, get_contract_spec) must raise or return a "broker unavailable" error (FR-009). Do not return stale cached data
- [X] T021 [US5] Implement connection restoration gate in src/scalping_core/tcp_broker_adapter.py: after reconnection, broker operations remain blocked until fresh ACCOUNT_INFO is received and validated. Only then transition to CONNECTED and re-enable operations (SC-005)
- [X] T022 [US5] Write unit tests in tests/test_tcp_broker_adapter.py: test that all broker operations fail-closed during DISCONNECTED state, that stale data is not returned, and that operations resume only after fresh account info post-reconnection

**Checkpoint**: System blocks all broker operations during disconnection and requires fresh data before resuming

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Test double, integration, and cross-story validation

- [X] T023 [P] Implement FakeBrokerAdapter in src/scalping_core/fake_broker.py: a test double implementing the broker adapter interface with configurable responses for account info, symbols, contract specs, and connection state — used by Phase 3+ tests that need a broker without real MT5
- [X] T024 [P] Write the MQL5 ReadOnlyConnector EA at mql5/ReadOnlyConnector.mq5: TCP client connecting to 127.0.0.1, sends HEARTBEAT periodically, sends ACCOUNT_INFO on connect, responds to REQUEST_SYMBOLS and REQUEST_CONTRACT_SPEC with MT5 API data. Read-only: no OrderSend, no order modification, no live trading flag (constitution Principle III)
- [ ] T025 Run quickstart.md validation scenarios end-to-end and record PASS/FAIL evidence for each scenario (automated harness PASS recorded; owner MT5 validation remains pending)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — T001, T002 can start immediately
- **Foundational (Phase 2)**: Depends on Setup — T003, T004 need broker_types
- **User Stories (Phases 3–7)**: All depend on Foundational (TCP framing)
  - US1 must complete before US2 (symbol discovery needs a connection)
  - US2 must complete before US3 (mapping needs discovered symbols)
  - US3 must complete before US4 (contract spec needs mapped symbols)
  - US5 can start after US1 (only needs connection state)
- **Polish (Phase 8)**: T023 can start after Setup; T024 can start after Setup; T025 needs all stories

### User Story Dependencies

- **US1 (P1)**: No dependencies — foundational connectivity story
- **US2 (P1)**: Depends on US1 (needs active connection to discover symbols)
- **US3 (P1)**: Depends on US2 (needs discovered symbols to map)
- **US4 (P2)**: Depends on US3 (needs mapped symbols to request contracts)
- **US5 (P2)**: Depends on US1 only (fail-closed is about connection state)

### Parallel Opportunities

- T001 and T002 are parallel (different files)
- T010 is [P] within US2
- T023 and T024 are [P] in Polish (different files, independent)
- US5 can run in parallel with US2/US3/US4 since it only depends on US1

---

## Parallel Example: Setup + Early Polish

```bash
# Setup tasks in parallel:
# T001: broker_types.py
# T002: broker_adapter.py (abstract interface)

# Once foundational is done, US5 can start alongside US2:
# US2: T010-T012 (symbol discovery)
# US5: T020-T022 (fail-closed guard) — only needs US1 done

# Polish tasks T023/T024 can start once Setup is done:
# T023: fake_broker.py (test double)
# T024: ReadOnlyConnector.mq5 (EA)
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete T001–T002 (Setup: types and interface)
2. Complete T003–T004 (Foundational: TCP framing)
3. Complete T005–T009 (US1: connect to Demo account)
4. **STOP and VALIDATE**: Backend connects, receives account info, detects disconnect
5. Proceed to US2–US5

### Incremental Delivery

1. Setup + Foundational → TCP framing works
2. US1 (T005–T009) → backend connects to EA on Demo
3. US2 (T010–T012) → symbol discovery works
4. US3 (T013–T016) → canonical mapping works
5. US4 (T017–T019) → contract specs retrieved
6. US5 (T020–T022) → fail-closed behavior validated
7. Polish (T023–T025) → test double, EA, end-to-end validation

---

## Notes

- All broker operations are read-only — no OrderSend in the EA, no order methods in the adapter
- Phase 2 stores all state in memory; durable PostgreSQL storage is Phase 5
- End-to-end validation (EA ↔ backend on live MT5) requires owner — automated tests use synthetic socket harness
- Account currency conversion is deferred to §19 decision #14; store raw currency
- The EA is manually loaded by the owner — no auto-loading

---

## Phase 9: Convergence

**Purpose**: Close gaps between the existing implementation and the spec/plan/tasks

- [X] T026 Make ContractSpec fields margin_initial, commission_per_lot, swap_long, swap_short non-optional (or enforce non-None validation at parse time) so incomplete contracts are rejected per FR-007, FR-008 (partial)
- [X] T027 Add RECONNECTING to ConnectionStatus enum (or document that the current DISCONNECTED→CONNECTED transition via staleness-gated data satisfies FR-002's intent) per FR-002, T001 (partial)
- [X] T028 Align AccountInfo field names to spec (account_number, broker_name, margin) or add a mapping note in data-model.md documenting the correspondence (login→account_number, server→broker_name, margin_free→margin) per FR-001, T001, T008 (partial)
- [X] T029 Add owner mapping modification: update_mapping(canonical_name, broker_name) method and confirmed_by_owner tracking on SymbolMapping per FR-006, SC-006, T015 (partial)
- [X] T030 Surface trading_permitted flag during symbol discovery — either add a BrokerSymbol dataclass with trading_permitted or extend discover_symbols() return type to include it per FR-004, US2/AC2, T010 (partial)
- [X] T031 Make fail-closed behavior explicit: broker-dependent methods should raise BrokerUnavailableError (or return a typed error) when disconnected, rather than silently returning None/empty per FR-009, T020 (partial)
- [X] T032 Add explicit fresh-data gate after reconnection: block broker operations until fresh ACCOUNT_INFO is received post-reconnect, beyond the general staleness timer per SC-005, T021 (partial)
- [X] T033 Align wire protocol message type names between contracts/tcp-protocol.md and tcp_broker_adapter.py code ("symbols" vs "symbol_list", flat vs "data" wrapper) per contracts/tcp-protocol.md (partial)
- [ ] T034 Run quickstart.md validation scenarios and record PASS/FAIL evidence (automated harness PASS recorded; owner MT5 validation remains pending) per T025 (partial)
