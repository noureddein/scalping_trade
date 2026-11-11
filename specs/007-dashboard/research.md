# Research: Phase 6 — Dashboard

**Date**: 2026-11-10

No NEEDS CLARIFICATION items in the technical context. Research covers
design patterns for the dashboard layer.

## Findings

### Dashboard Independence Pattern

- **Decision**: The dashboard is a read/command interface, not part of
  the execution path. It reads backend state via an internal HTTP API
  and sends configuration commands. The backend never depends on the
  dashboard being available — all risk enforcement, position
  protection, and trade execution continue independently.
- **Rationale**: FR-010 and Constitution Principle VI require that
  dashboard failure cannot affect execution safety. Coupling the
  dashboard into the execution path would violate this.
- **Alternatives considered**: Embedding dashboard logic in the
  backend main loop was rejected — it would create a failure coupling
  between UI rendering and trade execution.

### Live Update Delivery

- **Decision**: Use Server-Sent Events (SSE) for live dashboard
  updates. The backend pushes state changes (positions, P/L, spreads,
  risk state) as JSON events over a persistent HTTP connection.
- **Rationale**: SSE is stdlib-compatible (no websocket library
  needed), one-directional (backend → dashboard), and handles
  reconnection natively in the browser. FR-011 requires reconnection
  without duplication — SSE's `Last-Event-ID` header enables this.
- **Alternatives considered**: WebSocket was rejected (bidirectional
  not needed for read-only state push; adds dependency). Polling was
  rejected (cannot meet SC-002's 1-second update requirement without
  aggressive polling that wastes resources).

### Configuration Command Pattern

- **Decision**: Configuration changes (risk parameters, pair
  management, emergency stop) are sent as HTTP POST requests to the
  backend API. The backend validates, applies, and logs each change.
  The dashboard receives the validation result synchronously.
- **Rationale**: FR-008 requires validation + audit logging for every
  change. A synchronous request/response pattern ensures the operator
  sees immediate confirmation or rejection. The backend is the
  authoritative validator — the dashboard never applies changes locally
  without backend confirmation.
- **Alternatives considered**: Async command queue was rejected — adds
  latency and complexity for a single-operator system where immediate
  feedback is expected (SC-003: < 1 second).

### Audit Log Design

- **Decision**: Store audit log entries in a dedicated PostgreSQL
  table (extends existing Phase 5 schema). Each entry records:
  timestamp, parameter name, old value, new value, operator identity,
  and request source. The dashboard reads audit entries for display;
  the backend writes them atomically with the configuration change.
- **Rationale**: FR-008 requires every configuration change to be
  logged. PostgreSQL provides durability and queryability. Writing the
  audit entry in the same transaction as the config change guarantees
  no gaps (SC-004).
- **Alternatives considered**: File-based logging was rejected — not
  queryable for the dashboard's audit log viewer and harder to
  guarantee atomic write with config change.

### Emergency Stop Implementation

- **Decision**: Emergency stop is an HTTP POST that transitions the
  daily risk state to DRAINING via the existing Phase 5 state machine.
  The dashboard displays a confirmation dialog before sending the
  request. DRAINING blocks all new entries; existing positions are
  unaffected. Reversal requires authorized manual action (per Phase 5
  daily risk contract).
- **Rationale**: FR-007 requires immediate DRAINING transition.
  Constitution Principle VI requires DRAINING to survive rollover and
  require manual clearing. A confirmation dialog prevents accidental
  activation while keeping the action fast (SC-005: < 1 second after
  confirmation).
- **Alternatives considered**: Single-click without confirmation was
  rejected — accidental activation halts all trading until manual
  intervention. Undo-window pattern was considered but adds complexity
  for a rare action.

### Stale Data Indication

- **Decision**: When the SSE connection drops, the dashboard marks all
  displayed data with a visual "stale" indicator and disables
  configuration controls. On reconnection, the dashboard fetches full
  current state before re-enabling controls. SSE reconnection uses
  Last-Event-ID to resume from the last received event.
- **Rationale**: FR-009 requires clear stale/disconnected indication.
  FR-011 requires reconnection without duplication. Disabling controls
  during disconnection prevents the operator from making changes based
  on outdated data.
- **Alternatives considered**: Continuing to allow configuration
  changes during disconnection was rejected — the operator could make
  decisions based on stale P/L or risk state.
