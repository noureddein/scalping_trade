# Forex Scalping System

## Master Project Plan & Technical Specification

**Project Type:** Standalone Algorithmic Trading System  
**Development Environment:** Local development uses Python backend in WSL and MT5 on Windows  
**Project Structure:** Independent Folder and Git Repository  
**Development Tool:** Claude Code with Specialized Subagents  
**Trading Platform:** MetaTrader 5  
**Primary Database:** Independent PostgreSQL  
**Runtime AI Dependency:** None  
**Project Status:** Implementation in progress; no phase is production-accepted

## Current Status and Evidence Rules — 2026-11-11

This status section is the current status authority and supersedes the original planning-only status above; companion reports may be historical snapshots. It records what is present in the repository and what has actually been verified. A file or implementation report is not proof of a live integration test. A skipped test is not a pass. A phase is not accepted while its required tests or safety gates remain open.

**Approved current work topology:** the Python 3.12 backend runs in WSL and native MT5 runs on Windows. They communicate over TCP using the loopback address `127.0.0.1`. This WSL-to-Windows setup is the project's active development and integration target; Ubuntu/Wine is not an assumed requirement. Use one MQL5 EA per active pair, begin with a single-pair pilot, PostgreSQL for durable state, and no Redis initially. Architecture C is approved for implementation, not for live trading or unattended demo execution.

**Role split:** Claude authors code in implementation phases. Codex performs an independent audit and may run explicitly requested, non-trading tests when the repository and safe test environment are available. The owner performs GUI/terminal checks and any broker-connected validation. Never record an unrun, skipped, or unreported test as passed.

**Current phase ledger:**

| Phase | Status | Evidence and remaining gate |
|---|---|---|
| 0 — Bootstrap | Complete; verifier run reported 9/9 passing | The Phase 0 verifier was reported passing on 2026-11-11. The project, Git metadata, documentation, and Python package exist with `requires-python >=3.12`. Files remain untracked with no initial commit by owner direction; this is the retained repository state, not an open Phase 0 exit check. |
| 1 — Architecture and design | Design gate complete; design decisions remain | The retained architecture and approved owner decisions are consolidated in §§14 and 19 of this plan. Strategy, spread, schedule, exposure, conversion, order-correlation, and recovery policies remain unresolved as listed in §19. |
| 2 — Broker connectivity | Code scaffold implemented; local end-to-end validation pending | Python broker/TCP adapters and a read-only MQL5 connector exist. The EA was reported compiled with 0 errors/0 warnings. Native Windows MT5 ↔ WSL backend account/symbol/contract round-trip, reconnect, and fail-closed behavior have not been evidenced end-to-end. |
| 3 — Market data and spread | Core code implemented; live-feed acceptance pending | Tick validation, batching/deduplication, and spread logic with unit coverage exist. Live tick-batch delivery, burst/overflow behavior, persistent run-counter behavior, real spread accuracy, and market-data recovery remain unverified. Adaptive thresholds and retention choices are not approved. |
| 4 — Strategy engine | Deterministic prototype implemented; not validated for trading | Momentum, breakout, mean-reversion, and regime modules exist. Configuration is intentionally inert until explicit thresholds and a regime map are supplied. Tests use synthetic data; no tick-replay/backtest or strategy-quality evidence exists. |
| 5 — Risk and execution | Partial implementation; not execution-ready | Risk/stop-loss/domain gates, execution orchestration, order lifecycle, PostgreSQL store/migrations, reservations, startup reconciliation, and operator-resolution code exist. The current EA is read-only and has no broker order handler. Migrations are unapplied; PostgreSQL integration tests have not run; the latest execution/admission suite had 31 passed and 3 failed because a test reconciler does not implement `halt_entry_barrier()`. |
| 6 — Dashboard | Not started | No dashboard implementation or UI tests found. |
| 7 — Backtesting | Not started | No tick replay/backtest engine, historical dataset, or performance evaluation found. |
| 8 — Demo forward testing | Not started | A Demo account is available, but that alone is not a forward test. No approved end-to-end demo execution or forward-test record exists. |
| 9 — Deployment readiness | Not started | Operational hosting beyond the current WSL + Windows MT5 development setup, monitoring, backup/restore, recovery, load, security, and release acceptance remain open. |

No live-trading approval has been granted. No broker order submission is authorized by this status record.

---

# 1. Project Vision

Build a completely new, standalone, automated Forex scalping system.

The system must identify short-term trading opportunities, execute trades automatically, monitor open positions, and manage risk without human intervention during normal operation.

The system must prioritize:

- Execution speed.
- Low trading costs.
- Reliable market data.
- Dynamic spread monitoring.
- Strict risk management.
- Deterministic trading decisions.
- Broker independence.
- Full operational visibility.
- Reliable position management.

The system must NOT depend on AI, LLMs, Claude, or MCP during runtime trading.

All real-time trading decisions must be generated by deterministic algorithms.

## 1.1 Project Independence

This is a completely new project.

It must remain independent from the user's existing trading system.

Mandatory requirements:

- Create a new local project folder.
- Create a new Git repository.
- Use an independent PostgreSQL database.
- Use independent environment variables.
- Use independent application services.
- Use independent MT5 connectivity.
- Do not modify the existing trading system.
- Do not reuse or modify its MT5 bridge.
- Do not share its database.
- Do not modify its Docker configuration.
- Do not introduce dependencies on existing production services.

The existing trading system must remain completely untouched.

---

# 2. Core Trading Requirements

| Requirement            | Specification               |
| ---------------------- | --------------------------- |
| Market                 | Forex only                  |
| Gold                   | Excluded                    |
| Trading Type           | Algorithmic Scalping        |
| AI Runtime             | Not allowed                 |
| Lot Size               | Fixed 0.01                  |
| Gross Take Profit      | $0.10–$0.50                 |
| Intended Loss Ceiling Per Trade | $0.50 (not a guaranteed maximum) |
| Daily Profit Limit     | $15 default                 |
| Daily Loss Limit       | $5 default                  |
| Daily P/L              | Net P/L                     |
| Floating P/L           | Included                    |
| Daily Reset            | Asia/Amman                  |
| Positions Per Pair     | Maximum one                 |
| Trading Opportunities  | Target 50–200+ per day      |
| Strategy               | Adaptive Hybrid             |
| Broker Support         | CFI and MT5 Demo            |
| Database               | Independent PostgreSQL      |
| Dashboard              | Independent Web Application |

The daily opportunity target is not a mandatory trade quota.

Never force trades simply to achieve a specific number of daily transactions.

Trade quality and positive net expectancy take priority over trade frequency.

---

# 3. Technology Selection

The owner has approved the initial runtime stack below. Re-open a selection only if implementation evidence exposes a material problem; record any change as an owner-approved decision.

## 3.1 Backend

**Approved for implementation:** Python 3.12 backend, separate from MT5, connected over TCP on loopback. The repository currently uses synchronous PostgreSQL access and a TCP adapter. A web framework/server API has not been selected or implemented. Performance claims require measurement; the architecture prototype is not an order-execution benchmark.

## 3.2 Frontend

**Not selected and not implemented.** Keep React/Vite, Next.js, and alternatives open until Phase 6 requirements and security boundaries are designed. Dashboard controls must never bypass backend risk/admission checks.

Choose the framework based on actual project requirements.

## 3.3 Database

**Approved:** use an independent PostgreSQL database for durable state. Migrations 001–006 and a synchronous psycopg store are present but have not been applied to a validated disposable database. Do not treat schema code as deployment evidence.

Potential data domains:

- Broker accounts.
- Trading symbols.
- Symbol aliases.
- Market data.
- Spread history.
- Trading strategies.
- Trading signals.
- Orders.
- Positions.
- Trade history.
- Daily performance.
- Risk configuration.
- System events.
- Execution logs.

Database schema must be designed before implementation.

Use migrations and proper indexing.

Do not store every incoming tick in PostgreSQL without a clear performance justification.

Prefer in-memory tick processing and aggregated historical storage.

## 3.4 WebSocket

WebSocket remains an optional future dashboard transport. It is not implemented; do not add it to the broker/EA path without a documented requirement.

Potential applications:

- Live spread updates.
- Live account information.
- Open position updates.
- Daily P/L updates.
- Trading status.
- System alerts.
- Dashboard controls.

Do not introduce unnecessary infrastructure.

## 3.5 Redis

**Approved decision:** do not use Redis initially. PostgreSQL is the durable state store. Reconsider only with measured need and an owner-approved architecture change.

---

# 4. MT5 MCP Integration

Official documentation:

https://www.metatrader5.com/en/terminal/help/mcp_and_ai

MT5 MCP is approved for Claude Code development and testing assistance.

It must NOT be part of the runtime trading execution path.

## 4.1 Approved MCP Usage

The items below describe permitted development capabilities, not blanket authorization to access an account, alter a terminal, run Strategy Tester, or submit/modify/close orders. The owner-approved boundaries in this plan require separate explicit approval for Strategy Tester actions and any broker-mutating action. Current scope is non-mutating unless a later approval states otherwise.

Claude Code may use MT5 MCP to:

- Discover available trading symbols.
- Inspect account information.
- Read market data.
- Read historical tick data.
- Inspect open positions.
- Inspect trading history.
- Develop MQL5 Expert Advisors.
- Compile MQL5 code.
- Run Strategy Tester.
- Run backtesting.
- Analyze optimization results.
- Inspect terminal logs.

## 4.2 Runtime Restrictions

The production trading engine must never require:

- Claude Code.
- An LLM.
- OpenRouter.
- External AI APIs.
- MT5 MCP calls.

Runtime decisions must be deterministic.

## 4.3 MT5 Connectivity Research

Architecture C is the owner-approved implementation target under the decisions summarized in §14.1. The following options remain the research comparison that informed the decision; they are not an instruction to restart architecture selection.

### Option A: MQL5 Expert Advisor

Potential advantages:

- Native MT5 execution.
- Direct OnTick processing.
- Native trading functions.
- Access to broker-specific symbol properties.
- Broker-side stop-loss and take-profit placement.
- Reduced external communication overhead.

### Option B: Python MetaTrader5 API

Evaluate:

- Windows compatibility.
- MT5 terminal dependency.
- API reliability.
- Tick processing latency.
- Execution behavior.
- Process recovery.
- Integration with the backend.

### Option C: Hybrid Architecture

Evaluate a dedicated MQL5 execution component connected to an independent application backend.

The prototype measured socket behavior in a narrow non-trading setup. Those measurements do not verify the current tick-batch protocol, Windows MT5 ↔ WSL connectivity, or broker order execution. Keep these as separate acceptance gates in §§16–17.

---

# 5. Broker Abstraction

The long-term system should support multiple brokers and MT5-compatible accounts. **Current pilot scope is one Demo account and one active pair at a time.** Multiple accounts, account-wide aggregation across accounts, and multi-broker execution are not implemented or validated; the supported account count remains an owner decision in §19.

Initial targets:

- CFI.
- MT5 Demo accounts.
- Future MT5-compatible brokers.

Implement a Broker Adapter architecture.

The Python adapter abstractions and a read-only MT5 TCP data connector exist. The current MQL5 EA has no order submission/modification/close handler; therefore, the adapter interface is not proof of operational broker execution. Do not claim those operations are available until the EA protocol, authorization, risk checks, and end-to-end tests are implemented and audited.

Each broker adapter must handle:

- Connection management.
- Account discovery.
- Symbol discovery.
- Market data.
- Order submission.
- Order modification.
- Order cancellation.
- Position monitoring.
- Position closing.
- Account information.
- Contract specifications.
- Commission and swap information.
- Broker execution errors.

## 5.1 Canonical Symbol Registry

Trading strategies must never depend on broker-specific symbol names.

Use internal canonical symbols.

Example:

| Canonical Symbol | CFI      | MT5 Demo |
| ---------------- | -------- | -------- |
| EURUSD           | EURUSD\_ | EURUSD   |
| GBPUSD           | GBPUSD\_ | GBPUSD   |
| USDJPY           | USDJPY\_ | USDJPY   |

These are illustrative aliases only.

The system must discover actual symbols from each broker.

Users must be able to confirm or modify symbol mappings.

## 5.2 Contract Specifications

Discover and store:

- Digits.
- Point.
- Tick Size.
- Tick Value.
- Contract Size.
- Volume Minimum.
- Volume Maximum.
- Volume Step.
- Minimum Stop Distance.
- Trading Permissions.
- Margin Requirements.
- Commission.
- Swap.

Never assume all brokers have identical contract specifications.

---

# 6. Dynamic Forex Pair Management

The initial eight currency pairs must NOT be hardcoded.

Create a dynamic pair registry.

Users must be able to:

- Add currency pairs.
- Remove currency pairs.
- Enable trading.
- Disable trading.
- Discover available broker symbols.
- Configure symbol aliases.
- Configure maximum spread.
- View individual pair performance.

Every pair must have its own:

- Trading status.
- Current spread.
- Average spread.
- Spread threshold.
- Strategy status.
- Position status.
- Trading permission.

Adding a new pair must not require code changes.

Only valid Forex currency pairs should be accepted.

Exclude Gold and commodities.

---

# 7. Trading Strategy Architecture

Detailed strategy hypotheses, data conventions, routing rules, approval gates, and strategy-specific tests are specified in [`TRADING_STRATEGY_DESIGN.md`](TRADING_STRATEGY_DESIGN.md). That design document does not approve parameters or activate trading.

Evaluate an Adaptive Hybrid Scalping architecture as a research candidate; do not assume the hybrid is better than any single strategy.

Implement three independent strategy engines.

## 7.1 Momentum Scalping

Identify short-term directional momentum.

Evaluate:

- Price velocity.
- Momentum strength.
- EMA alignment.
- Short-term trend.
- Quote-update activity (not traded volume unless a broker-validated volume field is available).
- Volatility.
- Bid/Ask behavior.

## 7.2 Breakout Scalping

Identify short-term breakouts.

Evaluate:

- Local support and resistance.
- Recent price ranges.
- Breakout strength.
- Quote-update activity and tick density, not assumed traded volume.
- Momentum confirmation.
- False breakout conditions.

## 7.3 Mean Reversion Scalping

Identify short-term deviations from the recent mean.

Evaluate:

- Price deviation.
- Volatility.
- Bollinger Bands or equivalent measures.
- Reversal confirmation and mean-reversion evidence (no probability estimate is implemented or validated).
- Momentum exhaustion.
- Market regime.

## 7.4 Market Regime Detection

Create a deterministic Market Regime Detector.

Possible regimes:

- Trending.
- Ranging.
- High Volatility.
- Low Volatility.
- Breakout.
- Unstable Market.

The system should select an appropriate strategy based on market conditions.

Example:

Trending Market:

- Momentum strategy.

Ranging Market:

- Mean Reversion strategy.

Breakout Conditions:

- Breakout strategy.

Unstable Market:

- No Trade.

## 7.5 Strategy Validation

Detailed rules and test methodology are maintained in [`TRADING_STRATEGY_DESIGN.md`](TRADING_STRATEGY_DESIGN.md). Phase 4 verifies deterministic signal/regime behavior; Phase 7 performs historical replay and cost-aware performance evaluation. Do not assume the hybrid strategy is superior.

Backtest each strategy independently in Phase 7, only after the dataset and entry/exit/fill/cost model are approved.

Compare:

- Net Profit.
- Net Expectancy.
- Profit Factor.
- Win Rate.
- Maximum Drawdown.
- Average Holding Time.
- Trade count and uncertainty.
- Spread, commission, slippage, latency, and other execution costs.
- Average Spread Cost.
- Slippage.
- Trade Frequency.

Only combine strategies when evidence supports the combination.

All strategy parameters must be documented and configurable where appropriate.

---

# 8. Trade Entry and Execution

The entry process must follow a deterministic sequence.

1. Receive market tick.
2. Validate market data freshness.
3. Validate broker connection.
4. Validate pair trading status.
5. Validate spread.
6. Validate market regime.
7. Generate strategy signal.
8. Validate signal strength.
9. Validate daily risk state.
10. Validate existing position state.
11. Calculate position risk.
12. Validate margin requirements.
13. Validate execution conditions.
14. Submit the order.
15. Confirm execution.
16. Record the transaction.

Possible decisions:

- BUY.
- SELL.
- NO_TRADE.

Implement duplicate-order protection.

A pair cannot have more than one active position.

The duplicate prevention mechanism must work at execution and database levels.

Use safe order-state transitions.

Never assume that an order was executed merely because it was submitted.

---

# 9. Position Management

Maximum one active position per canonical Forex pair.

Different pairs may have active positions simultaneously.

Maximum concurrent positions must be bounded by:

- Number of eligible enabled pairs.
- Available margin.
- Account-level risk.
- Maximum exposure.
- Operational limits.

The system must not open a new position on a pair until its previous position is closed.

After a position closes, the pair becomes eligible for another valid opportunity.

## 9.1 Adaptive Trade Management

The Position Manager must continuously evaluate:

- Current floating P/L.
- Original entry conditions.
- Momentum changes.
- Market regime changes.
- Exit signals.
- Stop Loss.
- Take Profit.
- Maximum holding duration.

The system may close a trade early if the original trading thesis is no longer valid.

## 9.2 Maximum Trade Duration

Use adaptive maximum holding duration.

Duration should depend on:

- Strategy.
- Market regime.
- Volatility.
- Current trade conditions.

Do not use a universal fixed holding period.

---

# 10. Profit and Loss Management

## 10.1 Take Profit

Gross Take Profit range:

$0.10–$0.50 per trade.

Lot Size:

0.01.

The system must calculate expected gross and net profitability before entering a trade.

The selected TP must account for:

- Pair pip value.
- Contract specifications.
- Spread.
- Commission.
- Expected slippage.
- Account currency.

Do not assume all Forex pairs have identical pip values.

## 10.2 Intended Loss Ceiling Per Trade

Intended per-trade loss ceiling:

$0.50 per trade.

This is a mandatory pre-trade risk target, not a guarantee that realized loss cannot exceed $0.50. Gaps, slippage, rejected or missing protective orders, commissions, and execution failures can cause a larger realized loss. The implementation must reject an entry when estimated loss exceeds the intended ceiling; it must not describe this as guaranteed loss containment.

Implement:

- ATR-based stop calculation.
- Maximum cash-loss protection.
- Broker minimum stop-distance validation.
- Slippage protection.

If the required stop distance cannot satisfy the $0.50 risk ceiling:

Reject the trade.

Never widen the stop simply to satisfy broker constraints.

The system must document that gaps, slippage, and execution failures may cause actual losses to exceed the intended ceiling.

---

# 11. Daily Risk Management

Default settings:

Daily Profit Limit: +$15.

Daily Loss Limit: -$5.

Both values must be configurable from the dashboard.

## 11.1 Net P/L Calculation

Daily P/L must include:

- Realized profit and loss.
- Floating profit and loss.
- Commissions.
- Swap.
- Available transaction costs.

Use consistent accounting and avoid double-counting commissions or previously recorded charges.

Account currency must be converted into USD when necessary using a reliable conversion source.

## 11.2 Daily Reset

Timezone:

Asia/Amman.

The reset logic must use an explicit timezone-aware implementation.

Do not depend on the Windows machine timezone.

## 11.3 Daily Risk State Machine

States:

- ACTIVE.
- PROFIT_LOCKED.
- LOSS_LOCKED.
- DRAINING.
- DISABLED.

When Daily Profit Limit is reached:

- Block new entries.
- Cancel pending entry orders.
- Continue managing open positions.
- Do not force-close existing positions.

When Daily Loss Limit is reached:

- Block new entries.
- Cancel pending entry orders.
- Continue managing open positions.
- Do not force-close existing positions.

`PROFIT_LOCKED` and `LOSS_LOCKED` remain active until the next Asia/Amman trading day or an authorized manual reset. Per the owner-approved policies in §14.1, `DRAINING` and `DISABLED` survive daily rollover and require authorized manual clearing/reactivation; neither state is automatically triggered by daily P/L.

Use persistent and concurrency-safe state management.

Do not allow a new order to bypass the risk lock during simultaneous execution events.

---

# 12. Spread Intelligence Engine

This is a critical system component.

Calculate live spread independently for every Forex pair.

Spread must be calculated from current Bid and Ask prices.

Convert the price difference into pips using the broker's actual symbol specifications.

## 12.1 Spread Metrics

Track:

- Current Spread.
- Average Spread.
- Median Spread.
- Maximum Spread.
- Minimum Spread.
- Spread Volatility.
- Spread Percentile.
- Spread Trend.
- Spread Anomalies.

## 12.2 Hybrid Spread Protection

Use:

1. Manual Maximum Spread.
2. Adaptive Historical Spread Baseline.
3. Abnormal Spread Detection.

The system must block new entries when either the manual or adaptive safety condition is violated.

The adaptive threshold must be based on historical observations for the same pair and broker.

Do not use one universal spread threshold for all pairs.

## 12.3 Spread Stability

Re-enabling trading after an abnormal spread event requires:

60 seconds of stable spread conditions.

The system must verify stability continuously.

If spread becomes abnormal again, reset the stability timer.

The stability period should be configurable in future dashboard versions.

## 12.4 Existing Positions

A spread spike alone must never force-close an existing position.

Existing positions continue to be managed by the Position Manager.

Spread protection applies to new entries.

## 12.5 Market Holidays and Liquidity

Detect:

- Unusually wide spreads.
- Reduced tick activity.
- Stale market data.
- Abnormal volatility.
- Market closure.
- Unstable market reopening conditions.

Do not assume that every holiday has identical effects.

Use actual market data.

---

# 13. Dashboard Requirements

Build an independent dashboard.

## 13.1 Overview

Display:

- Current trading status.
- Selected broker.
- Selected account.
- Daily Net P/L.
- Daily Profit Limit.
- Daily Loss Limit.
- Open Positions.
- Number of trades today.
- Win/Loss statistics.
- Total spread costs.
- Current account equity.

## 13.2 Forex Pairs Management

Display:

- Canonical Pair.
- Broker Symbol.
- Trading Enabled.
- Current Spread.
- Average Spread.
- Maximum Spread.
- Spread Status.
- Active Position.
- Trading Permission.

Allow users to add, remove, enable, and disable pairs.

## 13.3 Live Spread Monitor

Display:

- Current Spread.
- Average Spread.
- Maximum Spread.
- Spread Trend.
- Spread Volatility.
- Manual Threshold.
- Dynamic Threshold.
- Stability Timer.
- Trading Permission.

## 13.4 Risk Controls

Allow users to modify:

- Daily Profit Limit.
- Daily Loss Limit.
- Maximum Loss Per Trade.
- Lot Size.
- Take Profit Range.
- Spread Thresholds.
- Trading Schedule.
- Position Limits.

All critical configuration changes must be validated and logged.

## 13.5 Positions

Display:

- Pair.
- Direction.
- Entry Price.
- Current Price.
- Lot Size.
- Floating P/L.
- Stop Loss.
- Take Profit.
- Holding Duration.
- Strategy.
- Exit Status.

## 13.6 Additional Modules

- Broker Accounts.
- Trading History.
- Strategy Performance.
- Execution Statistics.
- System Logs.
- Risk Events.
- Emergency Stop.

---

# 14. Database Design

## 14.1 Approved architecture and owner decisions

These decisions are consolidated here as the single current record; they supersede older architecture notes:

| Area | Approved decision / boundary |
|---|---|
| Current environment | Python 3.12 backend in WSL; native Windows MT5 terminal. Connect them using TCP loopback at `127.0.0.1`. Ubuntu/Wine is not the project's assumed environment. |
| Runtime architecture | Architecture C: MQL5 EA plus independent Python backend. Approved for implementation and controlled read-only validation; not approval for order submission or live trading. |
| EA topology | One EA per active pair; start with one pair. |
| Durable state | Independent PostgreSQL instance and least-privilege application role. Redis is not used initially. Never use the `postgres` superuser as the application identity. |
| Safety | `DRAINING` blocks new entries but continues management of open positions; it is manual and survives daily rollover. `DISABLED` survives rollover and requires authorized manual reactivation. Neither is automatically triggered by daily P/L. |
| Trading authority | No Strategy Tester action or broker-mutating request (submit, modify, close) without separate explicit owner approval. Current MQL5 connector is read-only. |

## 14.2 Database design baseline and scope

The full-system conceptual model comprises broker connections/accounts, canonical and broker symbols, trading pairs, spread snapshots/statistics, strategy configuration, regimes/signals, orders, positions/trades, daily risk/performance, execution/risk/system events, and application settings. The model is conceptual, not a claim that every entity is implemented. A single-operator design omits a users table; broker aliases belong in the broker-symbol mapping; pair settings belong with trading-pair configuration. Keep trade/position representation compatible with the unresolved partial-fill decision in §19.15.

The schema must use explicit foreign keys, `NOT NULL` and `CHECK` constraints, unique constraints for account/pair identity, and partial uniqueness to prevent more than one unresolved entry or open position per pair. Index actual query paths (recent pair ticks/spreads, open positions, non-terminal orders, and daily risk state). Use versioned migrations; apply only to an isolated disposable database until separately approved. Retain auditable order/risk events; tick-by-tick PostgreSQL storage is not approved without a measured need. Exact time-series retention and partitioning remain policy decisions.

**Cross-system order safety:** PostgreSQL and MT5 cannot share an atomic transaction. Persist the order intent and acquire the durable pair reservation before calling MT5; persist the broker outcome and position atomically afterward. `PENDING_SUBMIT`, `SUBMITTED`, and `UNKNOWN`/ambiguous outcomes block that pair. Never automatically resubmit an ambiguous request. A missing result from a generic broker query or a possibly altered MT5 comment is not exact correlation. If exact broker evidence is unavailable, retain the reservation and reconciliation barrier for authorized resolution. The executable read-only EA currently has no order handler, so this lifecycle is a design contract, not a working broker execution path.

**Admission and recovery:** PostgreSQL row-level barrier/reservation rules must serialize entry admission with startup reconciliation. An unresolved in-flight `SUBMITTING` request cannot be released based only on process death, timeout, or “not found”; keep admission blocked until the submitting process records its result, authoritative request-specific broker evidence resolves it, or an authorized operator intervenes. Failure to persist a confirmed fill must halt account-wide entry admission. Run DB/lock/restart integration tests only on a dedicated disposable database.

Create an independent PostgreSQL database.

Claude must propose and document the complete schema.

Suggested entities:

- users.
- broker_connections.
- trading_accounts.
- broker_symbols.
- canonical_symbols.
- symbol_aliases.
- trading_pairs.
- pair_configurations.
- spread_snapshots.
- spread_statistics.
- strategy_configurations.
- market_regimes.
- trading_signals.
- trading_orders.
- positions.
- trades.
- daily_performance.
- daily_risk_states.
- risk_events.
- execution_events.
- system_events.
- application_settings.

These are conceptual entities, not mandatory table names.

The final schema must be normalized where appropriate and optimized for actual query patterns.

Include:

- Indexing strategy.
- Unique constraints.
- Transaction handling.
- Database migrations.
- Retention policies.
- Recovery procedures.

---

# 15. Subagent Architecture

Claude Code may use subagents under a Lead Orchestrator for implementation work. Codex is the independent auditor and does not author source code during audit tasks unless the owner explicitly changes that assignment. The owner supplies approvals and runs manual test commands where requested.

## Lead Orchestrator

Responsibilities:

- Coordinate all subagents.
- Assign tasks.
- Review results.
- Resolve conflicts.
- Integrate implementations.
- Enforce project requirements.
- Approve phase transitions.

## Architecture Agent

Responsibilities:

- Backend technology selection.
- Frontend technology selection.
- System architecture.
- Dependency analysis.
- Architecture Decision Records.

## MT5 Integration Agent

Responsibilities:

- MT5 MCP configuration.
- Broker connectivity.
- Symbol discovery.
- MQL5 integration.
- Execution benchmarking.

## Market Data Agent

Responsibilities:

- Tick processing.
- Bid/Ask handling.
- Spread calculations.
- Data freshness.
- Market data recovery.

## Strategy Agent

Responsibilities:

- Momentum.
- Breakout.
- Mean Reversion.
- Market Regime Detection.
- Signal validation.

## Risk Management Agent

Responsibilities:

- Daily P/L.
- Stop Loss.
- Maximum Cash Loss.
- Exposure.
- Position restrictions.
- Risk state machine.

## Execution Agent

Responsibilities:

- Order submission.
- Execution validation.
- Slippage.
- Duplicate prevention.
- Position lifecycle.

## Database Agent

Responsibilities:

- PostgreSQL schema.
- Migrations.
- Indexing.
- Data integrity.
- Retention.

## Frontend Agent

Responsibilities:

- Dashboard.
- Real-time updates.
- Trading controls.
- Spread monitor.
- Pair management.

## QA Agent

Responsibilities:

- Unit testing.
- Integration testing.
- Backtesting.
- Tick replay.
- Performance validation.
- Failure simulations.

## Subagent Rules

- Every agent must receive explicit task boundaries.
- Every agent must report modified files.
- Avoid concurrent modifications to shared files.
- Use Git worktrees where necessary.
- Lead Agent must review all changes.
- No agent may activate live trading.
- All tests must pass before phase acceptance.

---

# 16. Implementation Roadmap

The roadmap status is evidence-based, not a claim that a phase is accepted. A phase may be marked complete only after its specified requirements, tests, environment checks, and independent review are complete. Code presence, compilation alone, a skipped integration test, or a historical passing total is insufficient.

## Phase 0: Project Bootstrap

**Status: Complete; verifier run reported 9/9 passing (2026-11-11).** The standalone project, Git metadata, package (`requires-python = ">=3.12"`), and environment/design documentation exist. The repository currently has no initial commit and files are untracked; do not stage or commit without owner direction. Windows MT5/Demo availability was observed. MT5 MCP restriction capability was not verified. Current developer topology and deployment target are recorded at the beginning of this plan.

**Exit evidence:** project path is independent; `pyproject.toml` identifies the Python package; environment/readiness reports exist. No external production system or database may be reused.

## Phase 1: Architecture and Design

**Status: Design gate complete for implementation; some policy choices remain unresolved.** This master plan is the canonical record for requirements, architecture, database, broker connectivity, strategy, risk, spread, testing, and approved owner decisions. The active local topology is WSL Python backend plus native Windows MT5. This does not approve order submission or live trading.

**Remaining:** resolve the owner decisions in §19 before enabling corresponding behavior; retain a traceable design/test requirement for each decision.

## Phase 2: Broker Connectivity

Implement:

- Broker abstraction.
- MT5 connection.
- Account discovery.
- Symbol discovery.
- Symbol mapping.
- Contract specifications.
- Demo account connectivity.

**Status: Read-only code scaffold implemented; local end-to-end acceptance pending.** `broker_adapter.py`, `tcp_broker_adapter.py`, `mt5_execution_adapter.py`, and `mql5/ReadOnlyConnector.mq5` exist. Python protocol tests use synthetic/socket-harness traffic. The EA compile was reported clean (0 errors, 0 warnings). No current evidence establishes Windows MT5 ↔ WSL round-trip for account, symbols, contracts, and reconnect. The MQL5 connector remains explicitly read-only and cannot service the Python execution adapter's order requests.

## Phase 3: Market Data and Spread

Implement:

- Tick ingestion.
- Market data normalization.
- Spread engine.
- Historical spread statistics.
- Dynamic spread thresholds.
- Market data monitoring.

**Status: Core code implemented; live-feed acceptance pending.** Tick validation, buffering/batch parsing, deduplication, staleness checks, and spread calculations have Python unit coverage. The EA tick path and current wire protocol have not passed end-to-end live-tick validation. Spread history is in-memory and is not durable; adaptive thresholds and production values remain unapproved.

## Phase 4: Strategy Engine

Implement and test:

- Momentum.
- Breakout.
- Mean Reversion.
- Regime Detection.
- Signal validation.

**Status: Deterministic prototypes implemented; strategy validation not started.** Strategy/regime code and synthetic-input unit tests exist. Defaults are intentionally inactive until structural parameters, thresholds, and a regime map are explicitly configured. No historical tick replay, per-strategy backtest, cost-adjusted comparison, or owner-approved strategy configuration exists.

**Design reference and scope:** [`TRADING_STRATEGY_DESIGN.md`](TRADING_STRATEGY_DESIGN.md) defines the current strategy hypotheses, data conventions, routing, safety gates, and test requirements. Phase 4 covers deterministic strategy/regime behavior and its unit/property tests. Historical replay infrastructure, dataset qualification, cost-aware performance measurement, and parameter selection belong to Phase 7. Phase 4 signal diagnostics must not be reported as strategy profitability; no strategy is approved or active.

## Phase 5: Risk and Execution

Implement:

- Fixed lot.
- Stop Loss.
- Maximum Cash Loss.
- Daily limits.
- Position management.
- Execution engine.
- Duplicate protection.

**Status: Partial implementation; not execution-ready.** Risk gate, stop-loss calculation, daily-risk policy, order types/lifecycle, execution engine, durable-store abstractions, PostgreSQL store/migrations, pair reservations, startup reconciliation, and operator resolution are present. However, migrations 001–006 have not been applied to an isolated test database; PostgreSQL integration tests are unverified. The read-only EA has no order handler, so the concrete execution path is not end-to-end operational. On 2026-11-10, the latest run of `pytest tests/test_execution_engine.py tests/test_admission_protocol.py -v` reported 31 passed and 3 failed because `tests/test_admission_protocol.py::_TestReconciler` does not implement the new abstract `halt_entry_barrier()` method. Fix and rerun before phase acceptance.

## Phase 6: Dashboard

Implement:

- Overview.
- Pair management.
- Broker management.
- Spread monitoring.
- Risk controls.
- Position monitoring.
- Analytics.

**Status: Not started.** No dashboard source or UI tests are present.

## Phase 7: Backtesting

Implement:

- Tick-level backtesting.
- Variable spread.
- Commission.
- Slippage.
- Execution latency.
- Historical simulations.

**Status: Not started.** No tick replay/backtest engine, curated historical dataset, or performance report is present.

**Dependency:** Phase 7 depends on an owner-approved historical data source and quality criteria (decision #9), a deterministic replay harness, explicit sampling/missing-interval semantics, and a reference exit/fill/cost model. Do not procure data, run MT5 Strategy Tester, select strategy parameters, or claim performance until the relevant approvals and evidence are recorded.

## Phase 8: Demo Forward Testing

Test on:

- CFI Demo.
- MT5 Demo.

Compare results and execution reliability.

**Status: Not started.** A connected Demo account is not evidence of a forward test. No trading order test is authorized by this plan. Before any Demo order test, create a separately approved, explicitly bounded test plan; keep execution disabled until that approval is recorded.

## Phase 9: Deployment Readiness

Perform:

- Security review.
- Recovery testing.
- Performance review.
- Final acceptance testing.
- Deployment documentation.

Live trading requires separate explicit user approval.

**Status: Not started.** Hosting and service management beyond the current local WSL + Windows MT5 setup, monitoring/alerting, backup/restore, crash recovery, security review, performance qualification, and release acceptance remain open. No Ubuntu/Wine deployment requirement is assumed.

---

# 17. Testing and Acceptance Criteria

## 17.1 Evidence status as of 2026-11-10

Historical reports include broader passing test totals, but later interface and barrier changes have not had a clean full-suite rerun. Use the latest results below; do not carry an older aggregate pass forward as current acceptance evidence.

| Area | Existing coverage/evidence | Current result | Required acceptance |
|---|---|---|---|
| Order/domain state | `test_order_types.py` | Owner reported 10 passed on 2026-11-09 | Re-run with full unit suite after current changes. |
| Broker symbols/adapters | `test_broker_adapter.py`, `test_mt5_execution_adapter.py` | Unit/mocked transport coverage exists; no current full-suite result | Re-run unit suite; then validate actual EA/backend data round-trip separately. |
| TCP backend protocol | `test_tcp_broker_adapter.py` | Synthetic/socket harness covers framing, malformed input, heartbeat, reconnect, tick batches and dedup | Re-run; then test actual EA socket protocol on local Windows MT5 + WSL. |
| Market data/spread | `test_market_data.py`, `test_spread_engine.py` | Deterministic unit coverage exists | Re-run; validate real tick freshness, burst loss counters, batch order, and spread calculation with broker contract specs. |
| Strategy | `test_strategy_engine.py` | Synthetic deterministic inputs; safe-start defaults | Re-run; then add replay/backtest validation before approving strategy parameters or combination. |
| Risk/execution unit tests | `test_risk_gate.py`, `test_daily_risk.py`, `test_stop_loss.py`, `test_execution_engine.py`, `test_admission_protocol.py`, `test_operator_resolution.py`, `test_startup_supervisor.py` | Latest two-file run: 31 passed, 3 failed due stale `_TestReconciler` abstract-method implementation | Fix test double; rerun both files, then the complete non-DB suite. Maintain execution-disabled invariant. |
| PostgreSQL persistence/barrier | `test_postgres_store.py`; migrations 001–006 | Five selected new integration tests were invoked and skipped because `SCALPING_DATABASE_URL` was unset. No DB connection was made. | Use only a dedicated disposable DB, verify its identity/isolation, apply migrations 001–006, then run all DB tests including lock/fallback/recovery cases. Do not use a broker-connected or production DB. |
| MQL5 compile | `ReadOnlyConnector.mq5` | Prior report: MetaEditor 0 errors/0 warnings | Recompile current EA source before attaching; verify exact source/binary match. |
| Local live feed | Windows MT5 + WSL backend | Not verified end-to-end | Run the read-only local checklist in Phase 2 below: heartbeat, account/symbol/contract, ticks, reconnect, stale state, and no-order evidence. |

The local `SCALPING_DATABASE_URL` check returned unset on 2026-11-10. Integration tests were not run against any database. The market being open does not make these software/unit/DB tests require MT5; only live-feed checks require the running terminal and available ticks.

### Test cases with recorded passing output

These cases passed individually or in a targeted run. A pass here is evidence for that case only; it does not accept an entire phase or replace the latest regression result below.

| Phase | Test case(s) | Recorded evidence | Boundary |
|---|---|---|---|
| 2 — Adapter contracts | Canonical Forex pair validation, symbol alias inference, contract/account types, fake adapter behavior | Covered by historical `test_broker_adapter.py` reports | Fake/harness tests only; no live MT5 data round-trip. |
| 2–3 — TCP protocol | Framing, 64-bit login, malformed messages, heartbeat/staleness, reconnection, tick-batch sequence/deduplication | Covered by historical `test_tcp_broker_adapter.py` reports | Python socket harness only; not proof the EA connected. |
| 3 — Market data/spread | Bid/ask and pip conversion, tick validity/freshness, spread statistics, thresholds, stability timer reset, existing-position spike behavior | Tests exist in `test_market_data.py` and `test_spread_engine.py`; prior full-suite reports passed before latest changes | Synthetic/unit inputs only; no live feed validation. |
| 4 — Strategy | Safe-start defaults, regime classification, momentum/breakout/mean-reversion signal cases, regime routing | Tests exist in `test_strategy_engine.py`; previous phase report recorded 21 passing tests | Synthetic inputs only; no historical replay/backtest or strategy performance acceptance. |
| 5 — Order state | Complete order-state matrix and stale-state error fields | Owner ran `python3.12 -m pytest tests/test_order_types.py -v`: 10 passed on 2026-11-09 | Domain tests; no PostgreSQL transition test. |
| 5 — Operator resolution | `test_resolve_wrong_state`, `test_resolve_filled_persists_position_atomically`, `test_override_persists_audit_atomically`, `test_override_disabled_by_default`, `test_override_does_not_release_reservation`, `test_operator_override_is_not_terminal`, `test_operator_override_visible_to_reconciler`, `test_operator_override_allows_future_resolution`, `test_operator_override_blocks_non_terminal_transitions`, `test_pending_submit_can_transition_to_operator_override` | Individual passing outputs supplied by owner on 2026-11-09/10 | In-memory/unit evidence; PostgreSQL persistence path remains unverified. |
| 5 — Admission/execution | `test_submit_exception_holds_submitting`, `test_gate_submission_rejects_no_reservation`, `test_gate_submission_failure_blocks_adapter_and_holds_reservation`, `test_resolve_admission_failure_does_not_assume_completion`, `test_resolve_admission_failure_surfaces_failed_shared_halt`, `test_unresolved_fill_halts_independent_engine_via_shared_barrier` | Individual passing outputs supplied by owner or observed in the latest targeted run on 2026-11-10 | Unit/test doubles only. Cross-process PostgreSQL barrier remains unverified. |
| 5 — Startup/readiness | `test_store_unavailable`, `test_reconciliation_exception_returns_error`, readiness tests for default-disabled, disabled adapter, missing/unavailable store, reservation provider, and reconciler | Individual passing outputs supplied by owner on 2026-11-09/10 | Unit/test doubles only; no real DB outage injection. |

### Latest regression and integration-test results

- `python3.12 -m pytest tests/test_execution_engine.py tests/test_admission_protocol.py -v`: **31 passed, 3 failed** (34 collected) on 2026-11-10. All three failures are caused by `tests/test_admission_protocol.py::_TestReconciler` not implementing the new abstract `halt_entry_barrier()` method. This is not a green suite; repair the test double and rerun.
- The three selected Postgres tests `test_halt_blocks_independent_provider`, `test_halt_blocks_gate_submission`, and `test_submitting_survives_halt`, plus `test_halt_fallback_without_halted_status` and `test_halt_fallback_gate_submission_blocked`: **5 skipped**, because `SCALPING_DATABASE_URL` was unset. No database connection was made.
- The new `test_halt_row_lock_held_through_update`, `test_halt_failed_halted_leaves_barrier_ready`, and `test_halt_barrier_cannot_return_to_ready_automatically` have not run against PostgreSQL. The lock test must exercise `halt_entry_barrier()` itself under contention; copying the SQL pattern alone is not sufficient integration evidence.
- The earlier reported aggregate of 332 passing tests predates recent halt-barrier and abstract-interface changes. Do not use it as the current acceptance result. No full-suite rerun has passed after these changes.

## 17.2 Required test backlog by phase

### Phase 2 — Read-only broker connectivity

- [ ] Compile the exact current `ReadOnlyConnector.mq5` in MetaEditor; archive log, terminal build, and source/binary hashes.
- [ ] Start the Python TCP backend in WSL bound only to `127.0.0.1:9100`; attach the read-only EA to one Forex chart in native Windows MT5 Demo with matching host/port. Verify heartbeat, account login/currency, Market Watch symbols, and contract-specification round-trip.
- [ ] Verify Windows MT5 permits the local TCP connection to `127.0.0.1`; inspect the allowed-address setting if connection is denied. Do not change terminal settings as part of an unattended test.
- [ ] Verify framing under fragmented and coalesced frames, slow/no listener, backend restart, EA reconnect, malformed messages, 64-bit login, and stale-data expiry.
- [ ] With market data available, verify tick batches, newest marker, tick freshness, and spread values against the MT5 chart/Market Watch; repeat during a busy period and record batch drops/sequence gaps.
- [ ] Verify loopback-only binding, no order API invoked, and no order/position/history change. The connector must remain read-only.
- [ ] Exercise backend stop/restart and terminal reconnect; confirm stale data denies entry eligibility and recovery requires fresh valid data.

### Phase 3 — Market data and spread

- [ ] With read-only EA and backend connected, verify tick batches arrive in oldest-to-newest order and the newest marker is correct.
- [ ] Exercise ring-buffer overflow and verify dropped/overwritten counters, batch size, sequence gaps, duplicate/reordered batch rejection, run-ID change, and restart persistence of the counter file.
- [ ] Verify no OnTick socket I/O; measure actual timer flush interval and tick-to-backend delay under low and busy feed conditions.
- [ ] Verify real bid/ask, digits, point, pip conversion, freshness, pair isolation, stability timer reset, and that spread spikes block new-entry eligibility without forcing an exit.
- [ ] Record that the current history window is in-memory only; test restart/reset consequences. Do not approve adaptive thresholds until validated with representative data per pair/broker/session.

### Phase 4 — Strategy

- [ ] Add deterministic unit/property tests for the strategy design: inactive defaults, insufficient history, invalid/non-finite/out-of-order ticks, gaps, threshold boundaries, BUY/SELL reference sides, and no-signal behavior.
- [ ] Specify and test empty-interval semantics for both indicator state and feed freshness. Omitting empty bars, synthesizing flat bars, or using elapsed-time-aware decay have different effects; none may fabricate a fresh executable quote.
- [ ] Test tick-count vs. fixed-time quote-bar vs. price-event-bar sampling as separate variants only when an approved historical dataset and replay implementation are available. Record actual window duration and never call quote-update density traded volume without validated broker volume.
- [ ] Test regime classification cadence, priority, hysteresis/confirmation and candidate dwell ranges, including transitions into/out of high volatility. No dwell duration, regime map, or threshold is approved by default; stale/unstable safety gates remain immediate.
- [ ] Test each entry hypothesis independently, including immediate breakout vs. retest variants, with strategy-specific edge cases. Do not compare strengths across strategies.
- [ ] Keep Phase 4 signal diagnostics distinct from complete trade-performance claims. No expectancy, profitability, or superiority claim without a complete entry, approved exit, fill, and cost model.
- [ ] Test the combined regime-to-strategy router only after component behavior is independently verified; no default parameters or map may silently activate.

### Phase 5 — Risk, persistence, and execution

- [ ] Fix `tests/test_admission_protocol.py::_TestReconciler` to implement `halt_entry_barrier()`; rerun execution/admission unit tests and record zero failures.
- [ ] Run complete non-DB unit suite after all current changes; report collected, passed, failed, and skipped counts.
- [ ] On a dedicated disposable PostgreSQL database only, verify fresh migration 001–006 install, upgrade from 001–005 to 006, constraints, rollback, account binding, owner-scoped reservations, order-state transition guards, and data cleanup.
- [ ] Run concurrent-process tests for pair reservation, barrier begin/acquire/gate ordering, HALTED fallback on pre-006 schema, in-flight SUBMITTING preservation, and independent connections. `test_halt_row_lock_held_through_update` must exercise the actual `halt_entry_barrier()` method under a held row lock, not only duplicate its SQL pattern.
- [ ] Inject DB unavailable, CHECK violation, transaction rollback, lock timeout, process termination at CP1–CP5, and restart; confirm no false READY, duplicate order, premature release, or lost unresolved intent.
- [ ] Verify all runtime order adapter behaviors against a separately approved non-live harness before any Demo order test. The current MQL5 EA is read-only; do not claim broker execution works until it has an explicit order protocol/handler and is separately reviewed.
- [ ] Test fixed lot validation, broker stop minimum vs intended loss ceiling, currency conversion, commission/swap, floating P/L, Asia/Amman day boundaries, sticky locks, account-wide concurrency, and operator reset audit.
- [ ] After owner decision #12, test the separate entry/close permission matrix under ACTIVE, DRAINING, PROFIT_LOCKED, LOSS_LOCKED, DISABLED, backend outage, and reconciliation states; prove an entry permission cannot implicitly grant close permission.
- [ ] After owner decision #13, test exact order correlation after timeout/restart, missing/truncated/rewritten comments, delayed history visibility, and rejection of approximate matches; unresolved outcomes must keep reservations and the barrier held.
- [ ] After owner decision #14, test supported account-currency conversions, stale/missing conversion quotes, rate direction, cost inclusion, and no double counting; all failures must reject new entries or lock risk state as specified.
- [ ] After owner decision #15, test partial fills, multiple deals per request, partial closes, remaining volume, duplicate deals, and restart reconciliation—or explicitly enforce/reject unsupported partial fills.

### Phase 6 — Dashboard

- [ ] Add UI/component tests for status, empty/stale feeds, disconnected broker, incorrect pair mapping, risk locks, role/authorization, and validation errors.
- [ ] Add API authorization and audit tests for every configuration-changing control; prove dashboard failure cannot stop position protection or bypass backend gates.
- [ ] Test live update reconnect, ordering, duplicate suppression, and stale display indicators.

### Phase 7 — Backtesting

- [ ] Resolve decision #9 first: evaluate historical data source, licensing/usage rights, broker/pair coverage, Bid/Ask quality, real-vs-generated intervals, missing periods, timezone, and acceptable quality thresholds. Record approval before acquiring or purchasing data.
- [ ] Build a deterministic replay harness for chronological Bid/Ask input, contract specifications, reproducibility, missing intervals, data-quality flags, and the approved indicator/sampling semantics.
- [ ] Test execution-cost accounting against a documented benchmark: Bid/Ask round-trip spread, commissions, swaps, slippage, latency, rejected/partial fills, stop gaps, and conversion costs. Avoid double counting and report unknown-cost sensitivity rather than silently setting costs to zero.
- [ ] Evaluate each strategy and entry variant separately on chronological development/validation/untouched test periods and walk-forward windows. Use a common owner-approved reference exit policy for fair comparison; do not use unapproved ATR multiples or exits.
- [ ] Add a slippage sensitivity grid only as a labeled scenario analysis until calibrated to broker/session observations; assess asymmetric or conditioned slippage where data permits. A break-even friction estimate is diagnostic, not a forecast or acceptance criterion.
- [ ] Add leakage checks, tried-configuration ledger, walk-forward/time-series split, parameter sensitivity, benchmark/no-trade comparison, uncertainty, drawdown and trade-count analysis; freeze dataset and code/config hashes in each report.
- [ ] Define owner-approved quantitative acceptance criteria before using backtest results to select parameters. Backtest results do not authorize Strategy Tester actions, Demo orders, or live trading.

### Phase 8 — Demo forward test

- [ ] Define the Demo-only scope, pair, lot, duration, stop conditions, monitoring, and evidence record; receive explicit owner approval before enabling any order submission.
- [ ] Verify startup reconciliation, protective SL/TP where supported, duplicate protection, daily locks, shutdown/restart recovery, disconnect behavior, and operator emergency stop.
- [ ] Record every signal, rejected entry, submitted request, broker outcome, cost, and discrepancy. Do not infer positive expectancy from a short or selectively reported sample.

### Phase 9 — Deployment readiness

- [ ] Define and approve any hosting topology beyond the current WSL backend + native Windows MT5 setup before deployment work. Do not assume Ubuntu/Wine.
- [ ] Test service restart, database outage, host/WSL reboot, backup restore, and alert delivery on the explicitly approved target environment.
- [ ] Verify secrets, least privilege, firewall/bind scope, log redaction, migrations, monitoring, incident/runbook, recovery and rollback procedures.
- [ ] Run measured load/latency and soak tests; set explicit owner-approved thresholds and attach raw results.
- [ ] Obtain separate explicit authorization before any live-trading enablement. Passing tests alone does not grant that authorization.

## Market Data

- Correct Bid/Ask calculations.
- Correct pip conversion.
- Correct symbol specifications.
- Stale data detection.
- Connection recovery.

The unit tests listed above do not substitute for the actual EA-to-backend test on the approved local topology.

## Spread

- Accurate live spread.
- Per-pair thresholds.
- Adaptive baseline.
- Abnormal spread detection.
- 60-second stability confirmation.
- No forced exit from spread spikes alone.

## Strategy

- Deterministic decisions.
- Reproducible backtests.
- No duplicate entries.
- Correct market regime classification.
- Performance measured after costs.

## Risk

- Daily profit lock.
- Daily loss lock.
- Floating P/L inclusion.
- Asia/Amman reset.
- Maximum $0.50 intended loss per trade.
- No new trades after daily lock.
- Existing positions remain managed.

## Execution

- Correct lot size.
- Correct symbol mapping.
- Correct stop distance.
- Slippage monitoring.
- Order rejection handling.
- Duplicate order prevention.

## Reliability

- MT5 disconnection.
- Backend restart.
- Database restart.
- Missing ticks.
- Broker rejection.
- Position recovery.
- Application crash.

## Performance

Measure:

- Tick processing latency.
- Signal generation latency.
- Order submission latency.
- Order confirmation latency.
- WebSocket update latency.
- Database processing overhead.

Do not claim low-latency performance without measured evidence.

---

# 18. Security and Safety

Mandatory:

- Live trading disabled by default.
- Demo accounts during development.
- No credentials committed to Git.
- Secure API key handling.
- Secure MCP configuration.
- No public exposure of MT5 control endpoints.
- Audit all configuration changes.
- Validate all trading commands.
- Emergency Stop functionality.
- Persistent position state.
- Broker-side protective SL wherever supported.

A strategy failure must not disable risk management.

A dashboard failure must not disable existing position protection.

A backend failure must not cause uncontrolled order submission.

---

# 19. Unresolved Decisions

Owner-approved architecture and operational-policy decisions are recorded in §14.1; do not ask the owner to reapprove those decisions unless a material change is proposed. Claude must not invent unresolved critical trading requirements.

The following require research, proposals, and user approval. These are unresolved policy/requirements decisions, not permission to activate features:

1. Exact entry and exit parameters for each strategy.
2. Initial spread thresholds for each pair.
3. Trading sessions.
4. High-impact news policy.
5. Number of simultaneous broker accounts.
6. Adaptive Take Profit selection logic.
7. Adaptive early-exit rules.
8. Market regime classification thresholds.
9. Historical tick data source and retention.
10. Maximum exposure and margin constraints.
11. Recovery behavior during prolonged MT5 disconnection.
12. Whether risk-reducing position closes are allowed while new entries are disabled, the database/risk authority is unavailable, or the system is draining. Current structural behavior blocks all broker-mutating requests; this is not owner-approved close policy.
13. Exact broker-authoritative correlation for an order after timeout, disconnect, or restart. An MT5 comment/correlation token may be changed or truncated and must not be treated as guaranteed evidence.
14. USD conversion source, quote freshness limits, fallback behavior, and cost-accounting rules for non-USD account currencies. Current domain code expects converted values from its caller.
15. Partial-fill and partial-close handling, including how filled volume, remaining exposure, and position/order records are reconciled. The current design assumes a single 0.01-lot fill and has no demonstrated live partial-fill behavior.
16. Strategy sampling basis: event/tick observations, fixed-time quote bars, or price-event bars; bar boundaries; and explicit empty-interval semantics for rolling indicators. A 5-second bar is an experimental candidate only. Do not forward-fill missing live quotes as fresh observations.
17. Regime-classification cadence and transition controls, including whether hysteresis, confirmation, or minimum dwell is useful. Test stability versus transition delay; no fixed dwell or bar count is approved.
18. Reference entry/exit/fill/cost model and quantitative acceptance criteria for comparing strategy hypotheses. ATR multipliers, slippage grids, and latency scenarios remain research assumptions until calibrated and approved.

Claude should present evidence-based recommendations and request approval when necessary.

---

# 20. Initial Master Prompt for Claude Code

**Historical kickoff prompt — superseded for current work.** Use the phase ledger and scoped owner prompts above for ongoing implementation. The original direction to wait before all implementation no longer overrides the owner's later approval to build. Maintain the current role split: Claude implements; Codex independently audits; no live trading without separate explicit authorization.

You are the Lead Software Architect and Engineering Orchestrator.

Your mission is to design and implement a new, standalone,
non-AI algorithmic Forex scalping system.

This project must be completely independent from the user's
existing trading system.

Follow this document as the primary project specification.

IMPORTANT:

Do not start implementation immediately.

First:

1. Analyze the requirements.
2. Spawn specialized research subagents.
3. Study official MT5 MCP documentation.
4. Compare MT5 runtime integration options.
5. Evaluate backend technologies.
6. Evaluate frontend technologies.
7. Design the database.
8. Identify architectural risks.
9. Identify missing requirements.
10. Prepare the implementation roadmap.

Create the following documents:

- MASTER_REQUIREMENTS.md
- ARCHITECTURE_DECISIONS.md
- SYSTEM_ARCHITECTURE.md
- DATABASE_DESIGN.md
- MT5_INTEGRATION_PLAN.md
- STRATEGY_DESIGN.md
- RISK_MANAGEMENT_DESIGN.md
- SPREAD_ENGINE_DESIGN.md
- SUBAGENT_EXECUTION_PLAN.md
- IMPLEMENTATION_ROADMAP.md
- TESTING_AND_ACCEPTANCE.md
- OPEN_DECISIONS.md

Do not modify the existing trading system.

Do not enable live trading.

Do not introduce AI into the runtime trading path.

Do not assume missing trading parameters.

All important architecture decisions must be documented.

Wait for user approval before starting implementation.

---

# 21. Definition of Success

The project is considered ready for production evaluation only when:

- It operates independently.
- It connects reliably to supported MT5 accounts.
- It discovers and maps broker symbols correctly.
- It processes live market data reliably.
- It monitors spread independently for each pair.
- It blocks entries under unsafe conditions.
- It enforces daily risk limits.
- It prevents duplicate positions.
- It manages existing positions independently of AI.
- It demonstrates positive net expectancy in robust testing.
- It passes demo forward testing.
- It survives connection and service failures.
- It provides complete operational visibility.

A high number of trades is not a success metric by itself.

Positive risk-adjusted net performance and reliable execution are the primary objectives.

**Final Rule: Never activate live trading without explicit user authorization.**
