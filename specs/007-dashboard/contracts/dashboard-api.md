# Dashboard API Contract

**Date**: 2026-11-10

**Scope**: Defines the internal HTTP API between the dashboard
frontend and the Python backend. All endpoints are localhost-only.
This is not a public API.

## Read Endpoints

### GET /api/overview

Returns the dashboard overview (§13.1 fields).

**Response**: JSON object with all DashboardState fields.

**Error**: 503 if backend state unavailable.

### GET /api/pairs

Returns all configured pairs with their display data (§13.2 fields).

**Response**: JSON array of PairView objects.

### GET /api/pairs/{pair}/spread

Returns live spread monitor data for a specific pair (§13.3 fields).

**Response**: JSON SpreadMonitorView object.

**Error**: 404 if pair not found.

### GET /api/positions

Returns all open positions (§13.5 fields).

**Response**: JSON array of PositionView objects.

### GET /api/risk-config

Returns current risk configuration values (§13.4 fields).

**Response**: JSON RiskConfigurationSet object. Read-only fields
(lot_size, trading_schedule if unapproved) are marked with
`"editable": false`.

### GET /api/history

Returns trading history (closed positions).

**Response**: JSON array of closed Position records with P/L.

### GET /api/risk-events

Returns risk events in reverse chronological order.

**Response**: JSON array of RiskEvent records. Supports
`?limit=N&offset=M` pagination.

### GET /api/audit-log

Returns configuration change audit log.

**Response**: JSON array of AuditLogEntry records. Supports
`?limit=N&offset=M` pagination.

### GET /api/system-logs

Returns recent system log entries.

**Response**: JSON array of log entries with severity and timestamp.
Supports `?limit=N&level=ERROR|WARN|INFO` filtering.

## Command Endpoints

### POST /api/pairs

Add a new pair.

**Request body**: `{"canonical_pair": "EURUSD", "broker_symbol": "EURUSD.m"}`

**Validation**: Pair must not already exist. Broker symbol must be valid.

**Response**: 201 with created pair data. 400 on validation failure.

**Audit**: Logged.

### PUT /api/pairs/{pair}/enabled

Enable or disable a pair.

**Request body**: `{"enabled": true|false}`

**Validation**: Pair must exist.

**Response**: 200 with updated pair data. 404 if not found.

**Audit**: Logged.

### DELETE /api/pairs/{pair}

Remove a pair.

**Validation**: Pair must have no active position or unresolved order
(FR-012). Returns 409 Conflict if blocked.

**Response**: 204 on success. 409 if position/order exists.

**Audit**: Logged.

### PUT /api/risk-config/{parameter}

Update a risk configuration parameter.

**Request body**: `{"value": <new_value>}`

**Validation**: Per-parameter rules from RiskConfigurationSet.
Invalid values return 400 with error message. Read-only parameters
return 403.

**Response**: 200 with `{"parameter": "...", "old_value": ..., "new_value": ..., "applied": true}`. 400 on validation failure.

**Audit**: Logged with old/new values and operator identity.

### POST /api/emergency-stop

Activate emergency stop (transition to DRAINING).

**Request body**: `{"confirm": true}`

**Validation**: `confirm` must be `true` (prevents accidental calls).
System must not already be in DRAINING or DISABLED.

**Response**: 200 with `{"state": "DRAINING", "activated_at": "..."}`.
409 if already draining/disabled. 400 if `confirm` missing.

**Audit**: Logged as RiskEvent (type: DRAINING_ACTIVATED).

## Live Update Stream

### GET /api/stream (SSE)

Server-Sent Events stream for live dashboard updates.

**Event types**:

| Event | Data | Trigger |
|-------|------|---------|
| `overview` | Full DashboardState JSON | P/L change, trade completion, state change |
| `spread` | PairView + SpreadMonitorView JSON | Tick received |
| `position` | PositionView JSON | Position open/close/price update |
| `risk-state` | DailyRiskState JSON | State transition |
| `pair-update` | PairView JSON | Pair config change |

**Reconnection**: Each event includes an `id` field. On reconnect,
the client sends `Last-Event-ID` header. The server replays missed
events or sends full state if the ID is too old.

**Heartbeat**: Server sends a comment line (`: heartbeat`) every 15
seconds to keep the connection alive.

## Consumer/Producer Obligations

**Dashboard frontend (consumer) guarantees**:
- Never caches configuration state locally; always reads from backend
- Disables controls when SSE connection is lost
- Shows stale indicator on all data when disconnected
- Sends `confirm: true` for emergency stop (no silent activation)

**Backend API (producer) guarantees**:
- Validates all configuration changes before applying
- Writes audit log entry atomically with config change
- Continues operating if dashboard disconnects
- Never blocks execution path on dashboard availability
- Emergency stop uses existing Phase 5 DRAINING transition
