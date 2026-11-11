# Feature Specification: Phase 2 — Broker Connectivity

**Feature Branch**: `003-broker-connectivity`

**Created**: 2026-11-10

**Status**: Draft

**Input**: User description: "Create a specification for the Phase 2: Broker connectivity"

**Master Plan Reference**: Phase 2 (line 1049), §5 Broker Abstraction, §5.1 Canonical Symbol Registry, §5.2 Contract Specifications, §14.1 Approved Decisions

## User Scenarios & Testing

### User Story 1 - Connect to a Demo Account (Priority: P1)

The system connects to a single MT5 Demo account over TCP loopback and
retrieves the account information (account number, broker name, balance,
equity, margin, currency). The connection must survive brief network
interruptions and report its state accurately.

**Why this priority**: Without a working broker connection, no
subsequent phase (market data, execution, risk) can function. This is
the foundational integration point between the backend and MT5.

**Independent Test**: Start the backend and the MT5 EA on a Demo
account. Verify that the backend receives and correctly parses account
information. Disconnect and reconnect; verify the backend detects both
states.

**Acceptance Scenarios**:

1. **Given** MT5 is running with a Demo account and the EA is loaded,
   **When** the backend starts, **Then** the backend receives account
   number, broker name, balance, equity, margin, and account currency
   within 5 seconds.
2. **Given** an established connection, **When** the EA or MT5 is
   stopped, **Then** the backend detects disconnection within 10
   seconds and reports the connection as unavailable.
3. **Given** a disconnected state, **When** the EA restarts, **Then**
   the backend re-establishes the connection and retrieves fresh
   account information without manual intervention.

---

### User Story 2 - Discover Available Symbols (Priority: P1)

The system discovers all trading symbols available on the connected
broker account, including their broker-specific names and trading
permissions.

**Why this priority**: Symbol discovery is required before the system
can map broker symbols to canonical names or retrieve contract
specifications.

**Independent Test**: Connect to a Demo account. Verify that the
backend receives a list of available symbols and each symbol includes
its name and trading permission status.

**Acceptance Scenarios**:

1. **Given** an active broker connection, **When** the backend requests
   symbol discovery, **Then** it receives a complete list of available
   symbols with their broker-specific names.
2. **Given** the symbol list, **When** inspected, **Then** each symbol
   includes whether trading is permitted on it.
3. **Given** a symbol that the broker does not offer, **When** the
   backend searches for it, **Then** it reports the symbol as
   unavailable rather than guessing or defaulting.

---

### User Story 3 - Map Broker Symbols to Canonical Names (Priority: P1)

The system maintains a canonical symbol registry that maps internal
symbol names (e.g., EURUSD) to broker-specific names (e.g., EURUSD_).
Strategies always reference canonical names. The owner can confirm or
modify mappings.

**Why this priority**: Trading strategies must never depend on broker-
specific symbol names. Without canonical mapping, the system cannot
support multiple brokers or even account for broker-specific naming
conventions.

**Independent Test**: Discover symbols from the broker. Verify that
the system creates or proposes canonical-to-broker mappings. Modify a
mapping and verify the change persists.

**Acceptance Scenarios**:

1. **Given** discovered broker symbols, **When** the system proposes
   mappings, **Then** each canonical Forex symbol has at most one
   broker-specific alias per broker.
2. **Given** a proposed mapping, **When** the owner modifies it,
   **Then** the updated mapping persists and is used in all subsequent
   operations.
3. **Given** a canonical symbol with no broker match, **When** the
   system is queried, **Then** it reports the symbol as unmapped rather
   than guessing.

---

### User Story 4 - Retrieve Contract Specifications (Priority: P2)

For each mapped symbol, the system retrieves and stores the broker's
contract specification: digits, point, tick size, tick value, contract
size, volume min/max/step, minimum stop distance, trading permissions,
margin requirements, commission, and swap rates.

**Why this priority**: Contract specifications are required for correct
lot sizing, stop-loss calculation, spread evaluation, and margin
checks in later phases.

**Independent Test**: Map at least one symbol. Retrieve its contract
specification. Verify all required fields are present and have valid,
non-default values from the broker.

**Acceptance Scenarios**:

1. **Given** a mapped symbol, **When** the backend requests its
   contract specification, **Then** it receives all 13 required fields
   (digits, point, tick size, tick value, contract size, volume
   min/max/step, minimum stop distance, trading permissions, margin
   requirements, commission, swap).
2. **Given** a contract specification, **When** the broker updates a
   field (e.g., margin requirement), **Then** the system detects the
   change on the next refresh.
3. **Given** a symbol whose contract data is incomplete or
   unparseable, **Then** the system marks that symbol as ineligible
   for trading rather than using defaults.

---

### User Story 5 - Fail-Closed on Connection Loss (Priority: P2)

When the broker connection is lost or the account becomes unreachable,
the system blocks all new trading operations and reports the outage
state. It does not silently proceed with stale data.

**Why this priority**: Constitution Principle VI requires fail-closed
behavior. Trading on stale account data or without a confirmed
connection risks unauthorized or incorrect orders.

**Independent Test**: Establish a connection, then terminate the EA.
Verify that the backend transitions to an unavailable state and that
any attempt to use broker data is rejected until the connection is
restored.

**Acceptance Scenarios**:

1. **Given** a lost broker connection, **When** the system attempts
   any broker-dependent operation, **Then** the operation fails with
   a clear "broker unavailable" status.
2. **Given** a restored connection, **When** the system verifies
   account availability, **Then** it re-enables broker operations only
   after confirming fresh account data.

---

### Edge Cases

- What happens if the EA sends malformed or incomplete data? The
  backend must reject the message and log the error without crashing
  or using partial data.
- What happens if the broker changes a symbol name between sessions?
  The system detects the mismatch during symbol discovery and flags
  the mapping as stale rather than silently using the old name.
- What happens if two EAs connect for the same account? The system
  must detect the duplicate and reject or handle it deterministically.
- What happens if the broker account currency is not USD? The system
  stores the actual account currency; conversion handling is deferred
  to §19 decision #14.

## Requirements

### Functional Requirements

- **FR-001**: The system MUST connect to a single MT5 Demo account
  over TCP loopback and retrieve account information (account number,
  broker name, balance, equity, margin, account currency).
- **FR-002**: The system MUST detect broker connection and disconnection
  within 10 seconds and report the current connection state accurately.
- **FR-003**: The system MUST automatically re-establish the connection
  when the EA restarts, without manual intervention.
- **FR-004**: The system MUST discover all available trading symbols
  on the connected account, including broker-specific names and trading
  permissions.
- **FR-005**: The system MUST maintain a canonical symbol registry
  mapping internal names to broker-specific names. Strategies MUST
  reference only canonical names.
- **FR-006**: The owner MUST be able to confirm or modify symbol
  mappings.
- **FR-007**: The system MUST retrieve and store contract
  specifications for each mapped symbol, covering all 13 required
  fields defined in §5.2.
- **FR-008**: The system MUST mark a symbol as ineligible for trading
  if its contract data is incomplete or unparseable — no defaults.
- **FR-009**: The system MUST block all new trading operations when
  the broker connection is lost or account data is stale. Fail closed.
- **FR-010**: The system MUST reject malformed or incomplete messages
  from the EA without crashing or using partial data.
- **FR-011**: The system MUST NOT submit, modify, or close any broker
  order. The connector remains read-only per constitution Principle III.

### Key Entities

- **Broker Connection**: Represents the TCP link between the backend
  and one MT5 EA. Has a state (connected, disconnected, reconnecting)
  and associated account information.
- **Account**: A single MT5 Demo account with number, broker name,
  balance, equity, margin, and currency.
- **Canonical Symbol**: An internal, broker-independent symbol name
  (e.g., EURUSD). The reference used by all strategies and internal
  logic.
- **Broker Symbol**: A broker-specific symbol name (e.g., EURUSD_)
  discovered from the connected account. Mapped to exactly one
  canonical symbol.
- **Symbol Mapping**: The association between a canonical symbol and
  its broker-specific name for a given broker/account.
- **Contract Specification**: The broker's trading contract details
  for a symbol (13 fields per §5.2).

## Success Criteria

### Measurable Outcomes

- **SC-001**: The system retrieves account information from a Demo
  account within 5 seconds of startup.
- **SC-002**: Connection loss is detected and reported within 10
  seconds; reconnection succeeds automatically when the EA restarts.
- **SC-003**: Symbol discovery returns the complete list of broker
  symbols and their trading permissions in a single round-trip.
- **SC-004**: All 13 contract specification fields are populated from
  the broker for every mapped symbol; zero fields use default or
  assumed values.
- **SC-005**: The system correctly blocks broker-dependent operations
  within 10 seconds of connection loss and re-enables them only after
  confirming fresh data.
- **SC-006**: The canonical symbol registry supports mapping changes
  that persist across system restarts.

## Assumptions

- The pilot scope is one Demo account and one active pair at a time,
  per master plan §5. Multi-account support is deferred to §19
  decision #5.
- The EA communicates with the backend over TCP loopback at 127.0.0.1.
  The wire protocol format is an implementation detail, not part of
  this specification.
- Order submission, modification, and cancellation are listed in the
  broker adapter interface (§5) but are NOT implemented in Phase 2.
  The connector remains read-only. Order handling belongs to Phase 5.
- Account currency conversion is deferred to §19 decision #14. Phase
  2 stores the raw account currency but does not convert values.
- The EA is loaded manually by the owner onto the MT5 chart. Auto-
  loading or remote EA management is out of scope.
