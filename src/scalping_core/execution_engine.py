"""Execution engine orchestrator (§8 deterministic sequence).

NON-TRADING: Concrete implementations exist (Mt5ExecutionAdapter,
PostgresDurableStateStore, PostgresPairReservationProvider,
PostgresStartupReconciler) but execution is hard-disabled at the
adapter level (_EXECUTION_DISABLED = True). This module cannot execute
real trades until all four dependencies are injected, report healthy,
and the adapter's execution flag is enabled after review.

Receives a strategy Signal, runs the full §8 entry sequence, and either
submits an order or rejects with reasons. Fail-closed at every step.

Safety invariants:
  - Inactive unless all four infrastructure dependencies are injected,
    non-simulation, and healthy — AND live_trading_enabled is True AND
    all required owner decisions are present.
  - Readiness is derived from the actual dependency objects; there are
    no caller-settable readiness booleans.
  - FakeExecutionAdapter (is_simulation=True) structurally prevents
    activation even if all other gates pass.
  - Pair reservation is acquired before order submission. Released only
    on broker-confirmed rejection/expiry or proven pre-submission failure
    (FAILED per adapter contract). Held through any ambiguity
    (PENDING_SUBMIT, SUBMITTED, UNKNOWN, exceptions) for reconciliation.
    After a fill, held until broker confirms the position is closed.
  - Startup reconciliation must be complete before any entry is accepted.
  - Signal.reference_price is logging context only; a fresh broker quote
    is obtained and validated independently before any execution decision.
  - Never assumes an order succeeded merely because it was submitted.
  - An order remains PENDING/UNKNOWN until a confirmed broker deal/fill
    is reconciled; request acceptance alone does not mark it FILLED.
  - Fails closed on stale/missing data, unavailable risk authority,
    unresolved position/order state, or failed risk checks.

Owner decisions (§19) that remain unset block execution:
  - Strategy parameters (§19 #1)
  - Spread thresholds (§19 #2)
  - Trading sessions (§19 #3)
  - Exposure limits (§19 #10)
  - Recovery behavior (§19 #11)

Close-position permission — UNRESOLVED POLICY:
  The project requires managing existing positions (§9, §12). The
  current execution-disabled gate blocks ALL broker-mutating operations
  including risk-reducing closes. This is a structural default, NOT an
  owner-approved policy decision. The owner has not decided whether
  risk-reducing closes should be permitted while new entries are
  disabled. Until this is resolved, close_position remains blocked by
  the same gate as submit_order. Separating the two gates requires an
  explicit owner decision and a new EA input parameter — see
  ExecutionAdapter.close_position docstring.
"""
from __future__ import annotations

import abc
import time
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .broker_types import ConnectionStatus, ContractSpec, SymbolMapping, Tick
from .daily_risk import DailyPnL, DailyRiskConfig, evaluate_state
from .execution_adapter import ExecutionAdapter
from .market_data import PairFeed, spread_in_pips
from .order_manager import OrderManager
from .order_types import (
    OrderRecord,
    OrderRequest,
    OrderResult,
    OrderSide,
    OrderState,
    OverrideAuditRecord,
    PositionInfo,
    StaleOrderStateError,
    is_terminal,
)
from .position_manager import PositionManager
from .risk_gate import (
    FIXED_LOT_SIZE,
    EntryCheck,
    EntryDecision,
    RiskState,
    evaluate_entry,
)
from .spread_engine import SpreadSnapshot, SpreadTracker
from .stop_loss import StopLossResult, calculate_stop_loss
from .strategy_types import Signal, SignalDirection


# ---------------------------------------------------------------------------
# Infrastructure dependency protocols
# ---------------------------------------------------------------------------

class DurableStateStore(abc.ABC):
    """Persistent backing for orders, positions, and daily-risk state.

    Implementations must be idempotent: repeated writes with the same
    key produce the same result. Recovery reads return the last-written
    state for startup reconciliation.
    """

    @abc.abstractmethod
    def is_available(self) -> bool:
        """True when the store is connected and writable."""

    # -- Daily risk ----------------------------------------------------------

    @abc.abstractmethod
    def save_risk_snapshot(
        self, trading_day: date, state: "RiskState", pnl: DailyPnL,
    ) -> None:
        """Upsert daily risk state + P/L for a trading day."""

    @abc.abstractmethod
    def load_risk_snapshot(
        self, trading_day: date,
    ) -> tuple["RiskState", DailyPnL] | None:
        """Load the last-saved risk state for a trading day. None if no row."""

    # -- Orders --------------------------------------------------------------

    @abc.abstractmethod
    def save_order(self, record: "OrderRecord") -> None:
        """Upsert an order record keyed by idempotency_key.

        Request columns are written on first insert only. Result columns
        are updated on every call. State must move forward per the
        transition matrix in order_types._ALLOWED_TRANSITIONS.

        Raises StaleOrderStateError if the transition is invalid — the
        caller must not silently ignore a blocked update.
        """

    @abc.abstractmethod
    def load_order(self, idempotency_key: str) -> "OrderRecord | None":
        """Load a single order by idempotency key. None if not found."""

    @abc.abstractmethod
    def load_non_terminal_orders(self) -> list["OrderRecord"]:
        """Load all orders in non-terminal state for reconciliation."""

    # -- Positions -----------------------------------------------------------

    @abc.abstractmethod
    def save_position(self, position: "PositionInfo") -> None:
        """Upsert an open position keyed by broker_ticket."""

    @abc.abstractmethod
    def load_open_positions(self) -> list["PositionInfo"]:
        """Load all positions not yet marked closed."""

    @abc.abstractmethod
    def mark_position_closed(self, broker_ticket: int) -> None:
        """Mark a position as closed. Idempotent."""

    @abc.abstractmethod
    def verify_account(self, account_id: str) -> None:
        """Bind this database to a single MT5 account, or verify the binding.

        Must be called once on startup before any writes. Raises
        AccountMismatchError if a different account_id is already registered.
        """


class PairReservationProvider(abc.ABC):
    """Cross-process, account-wide pair reservation preventing duplicate entries.

    Implementations must guarantee:
      - acquire is atomic: concurrent callers for the same pair must not
        both succeed. This holds across processes sharing the same account.
      - A pair may be reserved by at most one caller at a time.
      - release is owner-scoped: only the process that acquired the
        reservation can release it. Releasing a pair held by another
        process is a no-op — not an error.
      - release is idempotent: releasing an unreserved pair is a no-op.
      - Reservations survive process restarts. After restart, the new
        process MUST reconcile before acquiring new reservations. See
        StartupReconciler for the reconciliation contract.
    """

    @abc.abstractmethod
    def is_available(self) -> bool:
        """True when the provider is connected and able to serve reservations."""

    @abc.abstractmethod
    def acquire(self, canonical_pair: str) -> bool:
        """Atomically reserve a pair for entry. Returns False if already held."""

    @abc.abstractmethod
    def release(self, canonical_pair: str) -> None:
        """Release a previously acquired reservation. Idempotent."""

    # -- Reconciliation (startup only) -----------------------------------------

    @abc.abstractmethod
    def load_all_reservations(self) -> list[tuple[str, str]]:
        """Return all (canonical_pair, reserved_by) pairs. Reconciler reads these."""

    @abc.abstractmethod
    def adopt(self, canonical_pair: str) -> bool:
        """Claim a predecessor's reservation for this process.

        Called by the reconciler after the broker confirms an unresolved
        order or open position still exists for this pair. After adoption,
        normal release() works with the current process_id.

        Returns True if a reservation was adopted, False if none existed
        or it was already owned by this process.
        """

    @abc.abstractmethod
    def force_release(self, canonical_pair: str) -> None:
        """Remove a reservation regardless of owner.

        RECONCILER ONLY. Must be called only after the broker confirms no
        unresolved order or open position exists for this pair. Using this
        without broker confirmation risks releasing a reservation that
        protects an in-flight order or open position.
        """

    # -- Admission protocol (in-flight entry tracking) -------------------------

    @abc.abstractmethod
    def gate_submission(
        self, canonical_pair: str, order_request: "OrderRequest",
    ) -> bool:
        """Second admission gate: re-verify barrier, persist intent, mark SUBMITTING.

        In a single transaction, atomically:
          1. Takes FOR SHARE on the barrier row (must be READY).
          2. Persists the OrderRequest as PENDING_SUBMIT in the orders table.
          3. Sets admission_status='SUBMITTING' on the caller's reservation
             (must be in ACQUIRED state, owned by this process).

        All three must commit together. If the process crashes after this
        commit, the reconciler can recover the idempotency_key from the
        orders table and use it to correlate against broker records.

        Returns False if the barrier is no longer READY, the reservation
        is not in the expected ACQUIRED state, or the intent cannot be
        persisted — the caller must abort the entry attempt without
        releasing the reservation.

        The FOR SHARE lock ensures begin()'s FOR UPDATE blocks until this
        transaction commits, so the reconciler's drain step will see both
        the SUBMITTING status and the PENDING_SUBMIT order row.
        """

    @abc.abstractmethod
    def resolve_admission(
        self,
        canonical_pair: str,
        record: "OrderRecord",
        position: "PositionInfo | None" = None,
        override_audit: "OverrideAuditRecord | None" = None,
    ) -> None:
        """Persist broker outcome and mark admission IDLE — atomically.

        In a single transaction:
          1. Upserts the OrderRecord (with broker result) into the orders
             table, advancing state from PENDING_SUBMIT to the broker's
             reported state.
          2. If position is provided (FILLED), inserts the open position
             row in the same transaction.
          3. If override_audit is provided (OPERATOR_OVERRIDE), inserts
             the structured audit record in the same transaction. If
             the audit insert fails, the entire transaction rolls back
             and the override does not take effect.
          4. Sets admission_status='IDLE' on the caller's reservation.

        All steps must commit together. A partial failure rolls back
        everything — the order stays PENDING_SUBMIT + SUBMITTING for
        reconciler recovery.

        Only transitions SUBMITTING → IDLE for the current process's own
        reservation. The UPDATE must match canonical_pair, reserved_by,
        AND admission_status='SUBMITTING'.

        NOT called on submit exception — admission_status stays SUBMITTING
        so the reconciler knows a broker call was in progress and must
        verify broker state for this pair.
        """

    @abc.abstractmethod
    def load_in_flight_submissions(self) -> list[str]:
        """Return canonical_pairs with admission_status='SUBMITTING'.

        RECONCILER ONLY. Called after begin() sets RECONCILING, before
        scanning the broker. The reconciler polls this until the list is
        empty (all in-flight submissions resolved) or a timeout expires.

        Pairs remaining after timeout are UNRESOLVED, not "absent". The
        reconciler must NOT release these reservations or mark
        reconciliation READY. Neither a broker query returning "no order
        found," nor the submitting process being dead, nor its PostgreSQL
        backend being gone, proves the already-transmitted request will
        not still execute at the broker. A request in flight on the
        network is beyond any local fencing mechanism.

        These pairs must remain reserved with the barrier held at
        RECONCILING until one of:
          - The submitting process resolves (SUBMITTING → IDLE), proving
            the broker call completed and the order record is durable.
          - Authoritative broker evidence tied to the exact request
            proves its final outcome (e.g. the broker's order history
            API returns a terminal state for the idempotency key or
            request identifier used by the submission).
          - An operator resolves it manually after broker inspection.
        """


class StartupReconciler(abc.ABC):
    """Database-enforced startup reconciliation barrier.

    The barrier prevents all entry submissions while reconciliation is in
    progress. This is enforced in PostgreSQL: ``acquire()`` checks the
    barrier status inside its INSERT statement, so no process-local flag
    can bypass the gate.

    Lifecycle (every process on startup):

    1. Call ``begin()``. Returns True if this process is the reconciler.
       Returns False if another process holds the exclusive lock.
    2. If True: perform reconciliation:
       a. Drain in-flight submissions: poll
          ``load_in_flight_submissions()`` until empty or timeout.
          ACQUIRED entries cannot proceed (barrier is RECONCILING and
          ``gate_submission()`` will fail), so they are safe to handle
          after the drain.
          If SUBMITTING entries survive the timeout, the reconciler
          must NOT release their reservations or proceed to READY.
          Neither a broker query returning "no order found," nor the
          submitting process being dead, nor its PostgreSQL backend
          being absent, proves the already-transmitted request will
          not still execute at the broker. No local fencing mechanism
          can revoke a request that is in flight on the network.
          Resolution requires one of:
            - The submitting process resolves (SUBMITTING → IDLE).
            - Authoritative broker evidence tied to the exact request
              (idempotency key / request ID) proves its terminal state.
            - Manual operator intervention after broker inspection.
       b. ``load_all_reservations()`` — discover predecessor reservations.
       c. For each, query the broker:
          - Unresolved order or open position exists → ``adopt(pair)``.
          - Broker confirms pair is clear → ``force_release(pair)``.
       d. ``load_non_terminal_orders()`` — reconcile each against broker.
       e. Call ``complete()`` — sets barrier to READY, releases lock.
    3. If False: poll ``is_reconciled()`` until True.

    Concurrency safety:
      - Exclusive lock via ``pg_advisory_lock`` — only one reconciler.
      - ``acquire()`` takes ``FOR SHARE`` on the barrier row; ``begin()``
        takes ``FOR UPDATE``. The exclusive row lock in ``begin()`` blocks
        until every in-flight ``acquire()`` AND ``gate_submission()``
        commits, so the reconciler's drain step afterward sees every
        SUBMITTING entry that was admitted while the barrier was READY.
      - An entry attempt that passed ``acquire()`` but has not yet called
        ``gate_submission()`` is in ACQUIRED state. Its
        ``gate_submission()`` call will fail (barrier is RECONCILING),
        so it will abort without contacting the broker. The reservation
        stays for the reconciler to handle.
      - An entry attempt that passed ``gate_submission()`` is SUBMITTING.
        The reconciler's drain step waits for it to resolve to IDLE
        (broker responded). If it does not resolve within the timeout,
        it remains unresolved: the reservation stays held and the
        barrier stays RECONCILING until authoritative broker evidence
        tied to the exact request proves its outcome, or an operator
        intervenes.
      - If the reconciler crashes, the advisory lock is released when its
        connection drops. The next process acquires the lock and
        re-reconciles from scratch.
      - ``adopt()`` and ``force_release()`` are gated on barrier status
        RECONCILING in SQL — cannot run outside active reconciliation.
      - No TTL, no blanket deletion. Each reservation is individually
        verified against the broker before release.

    Durable order-intent lifecycle — crash points:

      CP1: Before gate_submission commits.
        No SUBMITTING status, no order row. Reservation is ACQUIRED.
        Reconciler sees the reservation, finds no order row, confirms
        no broker activity for the pair → safe to force_release.

      CP2: After gate_submission commits, before broker call begins.
        SUBMITTING status + PENDING_SUBMIT order row exist.
        Broker was never contacted. But the reconciler cannot prove
        the broker was never contacted — the crash may have happened
        after transmission began. The reconciler must treat this as
        unresolved: hold the reservation and barrier until authoritative
        broker evidence tied to the idempotency_key resolves it.

      CP3: During broker call (request transmitted, no response yet).
        Same durable state as CP2. The request may still execute at
        the broker. Unresolved — same handling as CP2.

      CP4: After broker response, before resolve_admission commits.
        SUBMITTING status + PENDING_SUBMIT order row. The broker
        responded but the outcome is not persisted. Same as CP2/CP3
        from the reconciler's perspective — unresolved.

      CP5: After resolve_admission commits.
        IDLE status + order row with broker result. Fully resolved.
        Reconciler handles via normal load_non_terminal_orders path.

    MT5 broker correlation mechanism and limits:

      MT5's ``order_send()`` accepts a ``comment`` field (max 31 chars)
      in ``MqlTradeRequest``. The idempotency_key can be embedded in
      this field and survives in the deal history (``history_deals_get``).

      After restart, the reconciler can:
        1. Load PENDING_SUBMIT orders from the orders table.
        2. For each, retrieve ``idempotency_key``.
        3. Call ``history_deals_get()`` for the time window and filter
           by comment to find matching deals.

      Limits (fail closed on all):
        - MT5 may truncate the comment field. If the round-tripped
          comment does not exactly match the idempotency_key, the
          reconciler must treat the order as unresolved.
        - ``history_deals_get()`` is not an indexed lookup — it is a
          sequential scan of the history window. A narrow time window
          (from ``signal_timestamp_ms``) bounds the scan.
        - The MT5 server or broker plugin may modify or drop the
          comment entirely. No guarantee of preservation.
        - If correlation fails (no matching deal, truncated comment,
          ambiguous results), the order stays unresolved: reservation
          held, barrier stays RECONCILING, operator must intervene.
        - MT5 does not support a native idempotency-key lookup. There
          is no API to query "did this exact request execute?" The
          comment field is the only request-level correlation available,
          and it is not authoritative.
    """

    @abc.abstractmethod
    def begin(self) -> bool:
        """Acquire exclusive reconciliation lock, set barrier to RECONCILING.

        Returns True if this process is now the reconciler.
        Returns False if another process holds the lock — caller must
        poll is_reconciled() until True.

        While the barrier is RECONCILING, all acquire() calls are blocked
        system-wide at the SQL level.
        """

    @abc.abstractmethod
    def complete(self) -> None:
        """Mark reconciliation complete, set barrier to READY, release lock.

        Raises RuntimeError if this process is not the active reconciler.
        After this call, acquire() is unblocked for all processes.
        """

    @abc.abstractmethod
    def is_reconciled(self) -> bool:
        """True when the database barrier status is READY.

        Checks the reconciliation_barrier table — not a process-local
        flag. Result is cached once READY within this instance to avoid
        per-call DB round-trips during normal operation.
        """

    @abc.abstractmethod
    def halt_entry_barrier(self) -> bool:
        """Set the entry barrier to a non-READY state after an unresolved fill.

        Called when a broker FILLED result cannot be durably persisted.
        Uses a NEW, independent transaction — the caller's original
        transaction has already failed.

        Sets the barrier so that acquire() and gate_submission() fail
        for ALL processes system-wide. The barrier must remain non-READY
        until startup reconciliation resolves the broker outcome.

        Returns True if the halt was durably persisted. Returns False if
        the database was unreachable — the caller must still fail closed
        process-locally; other instances will also fail closed because
        their database-backed admission checks cannot succeed without
        the database.
        """


# ---------------------------------------------------------------------------
# Configuration and result types
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ExecutionConfig:
    """Execution engine configuration.

    Infrastructure readiness is derived from the injected dependency
    objects, not from configuration flags. Only ordinary parameters
    (trading enabled, thresholds, owner decisions) live here.
    """
    live_trading_enabled: bool = False
    max_quote_age_ms: int = 2000
    max_risk_state_age_seconds: Decimal = Decimal("5")
    # §19 #10: unset until owner approves
    max_concurrent_positions: int | None = None
    # ATR multiplier for stop distance — §19 #1 owner decision
    atr_stop_multiplier: Decimal | None = None


@dataclass(frozen=True, slots=True)
class ExecutionAttempt:
    """Result of an execution attempt — approved or rejected with reasons."""
    executed: bool
    order_record: OrderRecord | None = None
    entry_decision: EntryDecision | None = None
    stop_result: StopLossResult | None = None
    reject_reasons: tuple[str, ...] = ()
    unresolved_fill: bool = False


class ExecutionEngine:
    """Orchestrates the §8 entry sequence. Inactive by default.

    All four infrastructure dependencies must be injected as concrete,
    healthy implementations for the engine to activate. Missing or None
    dependencies keep the engine inactive — there are no boolean overrides.
    """

    def __init__(
        self,
        config: ExecutionConfig | None = None,
        risk_config: DailyRiskConfig | None = None,
        *,
        adapter: ExecutionAdapter | None = None,
        durable_store: DurableStateStore | None = None,
        reservation_provider: PairReservationProvider | None = None,
        reconciler: StartupReconciler | None = None,
    ) -> None:
        self._config = config or ExecutionConfig()
        self._risk_config = risk_config or DailyRiskConfig()
        self._adapter = adapter
        self._durable_store = durable_store
        self._reservation_provider = reservation_provider
        self._reconciler = reconciler
        self._order_manager = OrderManager()
        self._position_manager = PositionManager()
        self._halted_unresolved_fill: bool = False

    @property
    def config(self) -> ExecutionConfig:
        return self._config

    @property
    def order_manager(self) -> OrderManager:
        return self._order_manager

    @property
    def position_manager(self) -> PositionManager:
        return self._position_manager

    def is_active(self) -> bool:
        """True only when all activation prerequisites are met.

        Derives readiness from the injected dependencies and their health.
        No caller-settable booleans — missing or unhealthy dependency
        means inactive.
        """
        if not self._config.live_trading_enabled:
            return False
        if self._config.max_concurrent_positions is None:
            return False
        if self._config.atr_stop_multiplier is None:
            return False
        if self._adapter is None or self._adapter.is_simulation:
            return False
        if not self._adapter.is_execution_enabled:
            return False
        if self._durable_store is None or not self._durable_store.is_available():
            return False
        if self._reservation_provider is None or not self._reservation_provider.is_available():
            return False
        if self._reconciler is None or not self._reconciler.is_reconciled():
            return False
        return True

    def attempt_entry(
        self,
        signal: Signal,
        mapping: SymbolMapping,
        feed: PairFeed,
        spread_tracker: SpreadTracker,
        risk_state: RiskState | None,
        risk_state_age_seconds: Decimal | None,
        daily_pnl: DailyPnL,
        broker_connected: bool,
        atr_points: Decimal | None = None,
    ) -> ExecutionAttempt:
        """Run the full §8 deterministic entry sequence.

        Uses the injected adapter, acquires pair reservation before
        submission, and releases it on rejection. Reservation is held
        through ambiguity for reconciliation.

        Returns ExecutionAttempt. Never raises on expected failure conditions.
        """
        reasons: list[str] = []

        if self._halted_unresolved_fill:
            return ExecutionAttempt(
                executed=False,
                reject_reasons=("halted_unresolved_fill_needs_reconciliation",),
            )

        if not self.is_active():
            reasons.append("execution_engine_inactive")
            return ExecutionAttempt(executed=False, reject_reasons=tuple(reasons))

        # At this point all deps are non-None (is_active passed)
        adapter = self._adapter
        assert adapter is not None
        reservation = self._reservation_provider
        assert reservation is not None

        if signal.direction == SignalDirection.NO_TRADE:
            reasons.append("signal_is_no_trade")
            return ExecutionAttempt(executed=False, reject_reasons=tuple(reasons))

        # §8.1: Fresh quote — reference_price is logging only
        fresh_tick = adapter.get_fresh_quote(mapping.broker_symbol)
        if fresh_tick is None:
            reasons.append("fresh_quote_unavailable")
            return ExecutionAttempt(executed=False, reject_reasons=tuple(reasons))

        quote_age_ms = _tick_age_ms(fresh_tick)
        if quote_age_ms is not None and quote_age_ms > self._config.max_quote_age_ms:
            reasons.append("fresh_quote_stale")
            return ExecutionAttempt(executed=False, reject_reasons=tuple(reasons))

        # §8.5: Spread check from fresh tick
        spread_snap = spread_tracker.update(
            spread_in_pips(fresh_tick, mapping.contract),
            fresh_tick.recv_time_mono,
        )

        # Position concurrency check
        if self._config.max_concurrent_positions is not None:
            if self._position_manager.count >= self._config.max_concurrent_positions:
                reasons.append("max_concurrent_positions_reached")

        # §8 steps 2–13: Risk gate
        entry_check = EntryCheck(
            canonical_pair=signal.canonical_pair,
            volume_lots=FIXED_LOT_SIZE,
            risk_state=risk_state,
            backend_available=True,
            broker_connected=broker_connected,
            risk_state_age_seconds=risk_state_age_seconds,
            max_risk_state_age_seconds=self._config.max_risk_state_age_seconds,
            market_data_fresh=feed.is_fresh(),
            trading_enabled=mapping.contract.trade_allowed,
            manual_spread_ok=spread_snap.manual_ok,
            adaptive_spread_ok=spread_snap.adaptive_ok,
            stable_spread_seconds=Decimal(str(spread_snap.stable_seconds)),
            has_open_position=self._position_manager.has_open_position(signal.canonical_pair),
            has_pending_entry=self._order_manager.has_pending_for_pair(signal.canonical_pair),
            estimated_loss_usd=None,  # filled after stop calc
            loss_estimate_valid=False,
        )

        # §10.2: Stop loss calculation
        if atr_points is None or self._config.atr_stop_multiplier is None:
            reasons.append("atr_data_unavailable")
            entry_decision = evaluate_entry(entry_check)
            return ExecutionAttempt(
                executed=False,
                entry_decision=entry_decision,
                reject_reasons=tuple(reasons + list(entry_decision.reasons)),
            )

        side = OrderSide.BUY if signal.direction == SignalDirection.BUY else OrderSide.SELL
        entry_price = fresh_tick.ask if side == OrderSide.BUY else fresh_tick.bid

        stop_result = calculate_stop_loss(
            side=side,
            entry_price=entry_price,
            atr_points=atr_points * self._config.atr_stop_multiplier,
            contract=mapping.contract,
        )

        # Re-evaluate entry check with loss estimate
        entry_check = EntryCheck(
            canonical_pair=entry_check.canonical_pair,
            volume_lots=entry_check.volume_lots,
            risk_state=entry_check.risk_state,
            backend_available=entry_check.backend_available,
            broker_connected=entry_check.broker_connected,
            risk_state_age_seconds=entry_check.risk_state_age_seconds,
            max_risk_state_age_seconds=entry_check.max_risk_state_age_seconds,
            market_data_fresh=entry_check.market_data_fresh,
            trading_enabled=entry_check.trading_enabled,
            manual_spread_ok=entry_check.manual_spread_ok,
            adaptive_spread_ok=entry_check.adaptive_spread_ok,
            stable_spread_seconds=entry_check.stable_spread_seconds,
            has_open_position=entry_check.has_open_position,
            has_pending_entry=entry_check.has_pending_entry,
            estimated_loss_usd=stop_result.estimated_loss_usd,
            loss_estimate_valid=stop_result.approved,
        )

        entry_decision = evaluate_entry(entry_check)

        if not stop_result.approved:
            reasons.append(stop_result.reject_reason or "stop_loss_rejected")

        if not entry_decision.approved:
            reasons.extend(entry_decision.reasons)

        if reasons:
            return ExecutionAttempt(
                executed=False,
                entry_decision=entry_decision,
                stop_result=stop_result,
                reject_reasons=tuple(reasons),
            )

        # Gate 1: Acquire pair reservation (checks barrier is READY)
        if not reservation.acquire(signal.canonical_pair):
            return ExecutionAttempt(
                executed=False,
                entry_decision=entry_decision,
                stop_result=stop_result,
                reject_reasons=("pair_reservation_unavailable",),
            )

        # Build intent before gate 2 so it can be persisted atomically.
        request = OrderRequest(
            canonical_pair=signal.canonical_pair,
            broker_symbol=mapping.broker_symbol,
            side=side,
            volume_lots=FIXED_LOT_SIZE,
            stop_loss_price=stop_result.stop_price,
            take_profit_price=None,  # §19 #6: adaptive TP not yet approved
            idempotency_key=_make_idempotency_key(signal),
            signal_timestamp_ms=signal.timestamp_ms,
            fresh_quote_bid=fresh_tick.bid,
            fresh_quote_ask=fresh_tick.ask,
            fresh_quote_time_ms=fresh_tick.server_time_ms,
        )

        # Gate 2: Re-verify barrier, persist order intent, mark SUBMITTING.
        # All three commit atomically. After this commit, a crash leaves
        # both SUBMITTING status and the PENDING_SUBMIT order row — the
        # reconciler can recover the idempotency_key for broker correlation.
        if not reservation.gate_submission(signal.canonical_pair, request):
            # Barrier closed or intent could not be persisted.
            # Reservation stays for reconciler to handle.
            return ExecutionAttempt(
                executed=False,
                entry_decision=entry_decision,
                stop_result=stop_result,
                reject_reasons=("barrier_closed_during_admission",),
            )

        # §8.14: Submit order — intent is durable, broker call begins.
        try:
            record = self._order_manager.submit(request, adapter)
        except Exception:
            # Cannot determine whether broker received the request.
            # Hold reservation AND admission_status='SUBMITTING'.
            # The durable PENDING_SUBMIT order row preserves the
            # idempotency_key for reconciler broker correlation.
            return ExecutionAttempt(
                executed=False,
                entry_decision=entry_decision,
                stop_result=stop_result,
                reject_reasons=("submit_exception_needs_reconciliation",),
            )

        # §8.15: Confirm execution — do not assume success
        state = record.result.state

        # Build position BEFORE resolve_admission so FILLED orders
        # persist order result + position + IDLE atomically.
        pos: PositionInfo | None = None
        if state == OrderState.FILLED and record.result.broker_ticket is not None:
            pos = PositionInfo(
                broker_ticket=record.result.broker_ticket,
                canonical_pair=signal.canonical_pair,
                broker_symbol=mapping.broker_symbol,
                side=side,
                volume_lots=FIXED_LOT_SIZE,
                open_price=record.result.fill_price or entry_price,
                current_price=entry_price,
                stop_loss=stop_result.stop_price,
                take_profit=None,
                floating_pnl_usd=Decimal(0),
                open_time_ms=record.result.fill_time_ms or fresh_tick.server_time_ms,
                swap_usd=Decimal(0),
                commission_usd=Decimal(0),
            )

        # Persist outcome (and position for FILLED) and mark admission
        # IDLE — all in one transaction so a crash cannot lose the
        # position while clearing SUBMITTING.
        try:
            reservation.resolve_admission(signal.canonical_pair, record, position=pos)
        except Exception:
            # Broker outcome is not durably persisted. If the broker
            # reported FILLED, real money is at risk but local state
            # doesn't know it. Do not register the position, do not
            # release the reservation. Halt all entries until the
            # account is reconciled — a held pair reservation alone
            # cannot protect account-wide risk limits.
            self._halted_unresolved_fill = True
            # Close the shared entry barrier so ALL processes halt.
            # Uses a separate transaction from the failed one.
            shared_halt_persisted = False
            if self._reconciler is not None:
                try:
                    shared_halt_persisted = self._reconciler.halt_entry_barrier()
                except Exception:
                    pass
            # If the shared halt was not persisted, the database is
            # unreachable. Other processes' acquire() and
            # gate_submission() use the same database and will also
            # fail — fail-closed is inherent. The process-local flag
            # protects this instance as defence-in-depth.
            reasons = ["resolve_admission_failed_needs_reconciliation"]
            if not shared_halt_persisted:
                reasons.append("shared_halt_not_persisted_db_unreachable")
            return ExecutionAttempt(
                executed=False,
                order_record=record,
                entry_decision=entry_decision,
                stop_result=stop_result,
                reject_reasons=tuple(reasons),
                unresolved_fill=state == OrderState.FILLED,
            )

        if pos is not None:
            self._position_manager.register_fill(pos)
            return ExecutionAttempt(
                executed=True,
                order_record=record,
                entry_decision=entry_decision,
                stop_result=stop_result,
            )

        if not is_terminal(state):
            # PENDING_SUBMIT, SUBMITTED, UNKNOWN — broker may still act.
            # Hold reservation for reconciliation.
            return ExecutionAttempt(
                executed=False,
                order_record=record,
                entry_decision=entry_decision,
                stop_result=stop_result,
                reject_reasons=("order_state_ambiguous_needs_reconciliation",),
            )

        # Terminal no-fill: REJECTED, EXPIRED, FAILED.
        # REJECTED/EXPIRED: broker confirmed no order exists.
        # FAILED: adapter guarantees proven local failure before any
        # request bytes left the process — no send started, no broker
        # state possible. Any partial send / timeout / uncertainty after
        # transmission begins must be UNKNOWN (handled above, held for
        # reconciliation). Releasing here on a mis-classified FAILED
        # would risk a duplicate entry.
        reservation.release(signal.canonical_pair)
        return ExecutionAttempt(
            executed=False,
            order_record=record,
            entry_decision=entry_decision,
            stop_result=stop_result,
            reject_reasons=(f"order_{state.value.lower()}",),
        )


    def confirm_position_closed(
        self, canonical_pair: str, broker_ticket: int | None = None,
    ) -> bool:
        """Release pair reservation after broker reconciliation confirms the position is closed.

        Precondition: the caller has verified with the broker that no open
        position exists for this pair. Do not call on local timeout or
        assumption — only on broker-confirmed closure.

        Idempotent: safe to call more than once for the same pair.
        Repeated calls are no-ops (mark_closed pops an absent key
        harmlessly, release is idempotent per provider contract).

        Returns False only if the engine has no reservation provider
        (should not happen in normal operation).
        """
        self._position_manager.mark_closed(canonical_pair)
        if broker_ticket is not None and self._durable_store is not None:
            try:
                self._durable_store.mark_position_closed(broker_ticket)
            except Exception:
                pass
        if self._reservation_provider is not None:
            self._reservation_provider.release(canonical_pair)
            return True
        return False


def _tick_age_ms(tick: Tick) -> int | None:
    """Approximate age in ms using monotonic clock. None if no reference."""
    now_mono = time.monotonic()
    age_s = now_mono - tick.recv_time_mono
    if age_s < 0:
        return None
    return int(age_s * 1000)


def _make_idempotency_key(signal: Signal) -> str:
    return f"{signal.canonical_pair}:{signal.timestamp_ms}:{uuid.uuid4().hex[:8]}"
