# Demo Scope Contract

**Date**: 2026-11-10

**Scope**: Defines the authorization and execution contract for Demo
forward testing. This is the first phase where the system submits
broker orders. Constitution Principle III requires explicit owner
approval before any order submission code is implemented or activated.

## Authorization Sequence

Before any order submission is possible:

1. **EA order handler approval**: Owner explicitly authorizes
   implementation of the Demo order handler MQL5 code. This is a
   separate approval from the Demo scope — it authorizes the code
   to exist.
2. **Demo scope definition**: Owner records a DemoScopeApproval with:
   - Demo account ID (verified as Demo, not Live)
   - Approved pair (single pair for pilot)
   - Approved lot size (0.01)
   - Maximum duration (start/end timestamps)
   - Stop conditions (when to halt before duration expires)
   - Monitoring requirements (what the owner will check)
3. **Scope verification**: On startup, the system verifies:
   - Connected account matches approved account
   - Account type is Demo (verified with broker, not self-reported)
   - Current time is within approved duration
   - Approval status is ACTIVE (not EXPIRED or REVOKED)
4. **Gate open**: Order submission pipeline activated for the approved
   pair only.

## Execution Contract

During an active Demo forward test:

### Order Submission Path

The Phase 5 execution pipeline is used unchanged. The Demo scope
gate is an additional check inserted before the broker adapter call:

```
Phase 5 admission sequence (steps 1–14)
  ↓
Demo scope gate check:
  - approval ACTIVE?
  - account matches?
  - pair matches?
  - within duration?
  - lot matches?
  ↓ (all pass)
Broker adapter → EA order handler → Demo broker
  ↓
Phase 5 outcome recording (unchanged)
```

**Any Demo gate failure**: Order blocked with structured reason.
Phase 5 reservation released.

### Evidence Recording

Every event in the pipeline is recorded to ForwardTestEvent:

| Pipeline Step | Event Type |
|---------------|------------|
| Strategy signal generated | SIGNAL_GENERATED |
| Signal fails validation | SIGNAL_REJECTED |
| Entry approved by risk gate | ENTRY_APPROVED |
| Entry rejected by risk gate | ENTRY_REJECTED |
| Order sent to broker | ORDER_SUBMITTED |
| Broker confirms fill | ORDER_FILLED |
| Broker rejects order | ORDER_REJECTED |
| Broker timeout | ORDER_TIMEOUT |
| Fill price != expected price | FILL_DISCREPANCY |
| Trade costs calculated | COST_RECORDED |
| Spread at decision time | SPREAD_AT_DECISION |
| Submission-to-fill latency | LATENCY_RECORDED |

**No silent drops**: If an event cannot be recorded (DB error), the
system logs the recording failure and continues — but the failure
itself is recorded as a system event when the DB recovers.

### Duration Expiry

When current time exceeds the approved end_time:

1. DemoScopeApproval status → EXPIRED
2. New entries blocked (equivalent to DRAINING)
3. Open positions continue to be managed (SL/TP active)
4. ForwardTestEvent: DURATION_EXPIRED
5. ForwardTestSession: ended_at set, end_reason = "duration_expired"

### Approval Revocation

When owner revokes the Demo approval:

1. DemoScopeApproval status → REVOKED
2. New entries blocked immediately
3. Open positions continue to be managed
4. ForwardTestEvent: APPROVAL_REVOKED
5. ForwardTestSession: ended_at set, end_reason = "owner_revoked"

## Report Contract

After a forward test session ends, the report generator produces a
ForwardTestReport with:

**Mandatory content**:
- Sample size and statistical sufficiency assessment
- Net P/L (after all costs) and gross P/L
- Cost breakdown: spread, commission, swap, slippage
- Average slippage (expected vs. actual fill price)
- Maximum drawdown
- Win rate and average trade duration

**Mandatory warnings** (always present):
- "These results do not authorize live trading."
- If sample_sufficient = false: "**Insufficient sample size for
  statistical inference.**"

**Prohibited claims**:
- No "positive expectancy" without documented statistical test
- No "profitable strategy" from a small sample
- No comparison to live trading performance (none exists)

## Consumer/Producer Obligations

**Demo scope gate (producer) guarantees**:
- No order is submitted without an ACTIVE DemoScopeApproval
- Account type is verified as Demo with the broker
- Approved pair, lot, and duration are enforced per-order
- Duration expiry blocks new entries automatically

**Execution pipeline (consumer) guarantees**:
- All Phase 5 safety mechanisms remain active
- Every event is recorded to ForwardTestEvent
- Fill discrepancies are measured and recorded
- Execution latency is measured and recorded
- Report includes mandatory disclaimers
