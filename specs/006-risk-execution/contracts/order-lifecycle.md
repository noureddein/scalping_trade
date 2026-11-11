# Order Lifecycle Contract

**Date**: 2026-11-10

**Scope**: Defines the order lifecycle between the risk/execution
layer (Phase 5) and the broker adapter (Phase 2). This is a design
contract — the EA is currently read-only with no order handler.

## Entry Admission Sequence

The deterministic entry pipeline (§8) must complete these steps in
order before any broker contact:

1. Receive validated signal recommendation (Phase 4)
2. Obtain fresh quote (not the signal's reference price)
3. Validate spread gate (Phase 3)
4. Validate market regime eligibility (Phase 4)
5. Validate daily risk state permits entry
6. Validate no open position, unresolved order, or held reservation
   for this pair
7. Validate reconciliation barrier is released
8. Calculate position risk (lot, stop, estimated loss, margin)
9. Validate estimated loss <= $0.50 intended ceiling
10. Validate stop distance >= broker minimum
11. Validate margin and exposure limits
12. Persist OrderIntent (state: DRAFT)
13. Acquire PairReservation
14. Transition OrderIntent to PENDING_SUBMIT

**Any failure at steps 1–11**: Reject entry with structured reason.
No OrderIntent created.

**Failure at step 12–14**: Roll back; release reservation if acquired.

## Order Submission Sequence

After admission, the submission path:

1. Transition to SUBMITTING (persisted)
2. Call broker adapter with order details
3. Record OrderOutcome
4. Transition based on outcome:
   - FILLED → create Position atomically, release reservation
   - REJECTED → release reservation
   - CANCELLED → release reservation
   - TIMEOUT/DISCONNECT → transition to UNKNOWN; reservation HELD

## Ambiguous Outcome Handling

When the broker outcome is unknown (timeout, disconnect, error):

1. OrderIntent transitions to UNKNOWN
2. PairReservation remains HELD
3. ReconciliationBarrier may be activated (account-wide)
4. System does NOT automatically resubmit
5. Resolution requires:
   - Authoritative broker evidence (exact order match), OR
   - Authorized operator intervention (auditable)
6. Operator resolution creates a RiskEvent and transitions to
   OPERATOR_RESOLVED

## Startup Reconciliation

On process startup:

1. Scan for non-terminal OrderIntents (DRAFT, PENDING_SUBMIT,
   SUBMITTING, SUBMITTED, UNKNOWN)
2. If any found: hold ReconciliationBarrier (block all entries)
3. For SUBMITTING specifically: NEVER auto-clear based on process
   death, timeout, or "not found"
4. For confirmed fills that failed to persist: halt account-wide
   admission
5. Barrier released only when all non-terminal intents are resolved

## Daily Risk Contract

The daily risk state machine governs entry permission:

| State | New Entries | Open Position Mgmt | Survives Rollover |
|-------|------------|-------------------|-------------------|
| ACTIVE | Allowed | Yes | Resets to ACTIVE |
| PROFIT_LOCKED | Blocked | Yes | Resets to ACTIVE |
| LOSS_LOCKED | Blocked | Yes | Resets to ACTIVE |
| DRAINING | Blocked | Yes | Yes |
| DISABLED | Blocked | Yes | Yes |

**Daily reset**: Occurs at Asia/Amman timezone boundary. Only
PROFIT_LOCKED and LOSS_LOCKED reset. DRAINING and DISABLED require
authorized manual action.

## Consumer/Producer Obligations

**Risk gate (producer) guarantees**:
- No entry is submitted without durable intent + reservation
- Estimated loss is validated against the $0.50 ceiling
- Stop distance meets broker minimum; stop is never widened
- Daily risk state permits the entry
- All validations use fresh data (not stale signal references)

**Execution engine (consumer) guarantees**:
- Broker outcome is recorded regardless of success/failure
- Position is created atomically with fill recording
- Ambiguous outcomes keep reservation held
- No automatic resubmission
- All state transitions are logged as RiskEvents
