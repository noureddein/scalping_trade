# Research: Phase 2 — Broker Connectivity

**Date**: 2026-11-10

No NEEDS CLARIFICATION items in the technical context. The technology
stack (Python 3.12, MQL5, TCP, pytest) and architecture (C) are already
approved. Research focuses on design patterns for the integration.

## Findings

### Connection Management Pattern

- **Decision**: Use a state-machine model for broker connection
  (connected → disconnected → reconnecting → connected). The backend
  polls or uses heartbeat/timeout to detect disconnection.
- **Rationale**: A simple state machine makes connection state testable
  and observable. The EA sends periodic heartbeats; the backend detects
  absence within the 10s threshold (SC-002).
- **Alternatives considered**: Event-driven connection monitoring was
  considered but adds complexity without benefit for a single-connection
  pilot. Callback-based detection requires async infrastructure not yet
  in place.

### Symbol Discovery and Mapping

- **Decision**: The EA sends the full broker symbol list on connection
  or on request. The backend proposes canonical mappings. The owner
  confirms or modifies mappings which persist in-memory (durable storage
  in Phase 5).
- **Rationale**: The master plan §5.1 requires canonical symbols and
  owner-confirmable mappings. Discovery must come from the broker, not
  from hardcoded lists.
- **Alternatives considered**: Auto-mapping by string similarity was
  considered but rejected — it risks silent mismatches. The owner must
  confirm.

### Contract Specification Retrieval

- **Decision**: The EA retrieves contract specs from MT5's
  `SymbolInfoInteger`, `SymbolInfoDouble`, and `SymbolInfoString`
  functions and sends all 13 fields per §5.2.
- **Rationale**: MT5 is the authoritative source for contract specs.
  Never assume two brokers have identical specs.
- **Alternatives considered**: Caching specs across sessions was
  considered. The spec requires detecting changes on refresh (SC
  acceptance scenario 4.2), so specs must be re-fetched from the broker
  periodically or on reconnection.

### Wire Protocol

- **Decision**: Length-prefixed JSON messages over TCP. Simple, human-
  readable, debuggable. The EA serializes MQL5 data to JSON strings;
  the backend parses them.
- **Rationale**: JSON is natively supported in MQL5 (string operations)
  and Python. A binary protocol would be faster but adds debugging
  complexity for a pilot with low message volume. Malformed messages
  are rejected per FR-010.
- **Alternatives considered**: MessagePack (smaller), protobuf (schema-
  enforced). Both add build/dependency complexity disproportionate to
  the pilot's needs.

### Fail-Closed Behavior

- **Decision**: When the connection drops, the backend transitions to
  DISCONNECTED state. All broker-dependent operations check state first
  and fail immediately if not CONNECTED. Re-enable only after fresh
  account data is confirmed.
- **Rationale**: Constitution Principle VI (fail-closed) and FR-009.
  No silent degradation.
- **Alternatives considered**: Graceful degradation with cached data
  was rejected — trading on stale account data violates fail-closed.
