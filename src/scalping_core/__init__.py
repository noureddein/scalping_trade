from .broker_adapter import (
    BrokerAdapter,
    discover_canonical_mappings,
)
from .broker_types import (
    AccountInfo,
    ConnectionStatus,
    ContractSpec,
    SymbolMapping,
    Tick,
)
from .tcp_broker_adapter import TcpBrokerAdapter
from .daily_risk import (
    AMMAN_TZ,
    DailyPnL,
    DailyRiskConfig,
    ZERO_PNL,
    evaluate_state,
    is_new_trading_day,
    reset_state,
    trading_day,
)
from .risk_gate import (
    FOREX_CURRENCIES,
    EntryCheck,
    EntryDecision,
    RiskState,
    evaluate_entry,
)
from .market_data import (
    PairFeed,
    TickRejectReason,
    TickResult,
    pip_size,
    spread_in_pips,
)
from .spread_engine import (
    SpreadConfig,
    SpreadSnapshot,
    SpreadTracker,
)
from .strategy_types import (
    MarketRegime,
    PricePoint,
    Signal,
    SignalDirection,
    StrategyType,
)
from .market_regime import RegimeConfig, RegimeDetector
from .momentum_strategy import MomentumConfig, MomentumStrategy
from .breakout_strategy import BreakoutConfig, BreakoutStrategy
from .mean_reversion_strategy import MeanReversionConfig, MeanReversionStrategy
from .strategy_engine import (
    DEFAULT_REGIME_MAP,
    PairStrategyConfig,
    PairStrategyEngine,
    StrategyEngine,
)
from .order_types import (
    AccountMismatchError,
    OrderRecord,
    OrderRequest,
    OrderResult,
    OrderSide,
    OrderState,
    PositionInfo,
    PositionState,
    StaleOrderStateError,
    is_terminal,
    is_valid_transition,
)
from .execution_adapter import ExecutionAdapter
from .stop_loss import StopLossResult, calculate_stop_loss
from .order_manager import OrderManager
from .position_manager import PositionManager
from .execution_engine import (
    DurableStateStore,
    ExecutionAttempt,
    ExecutionConfig,
    ExecutionEngine,
    PairReservationProvider,
    StartupReconciler,
)
from .fake_execution_adapter import FakeExecutionAdapter
from .startup_supervisor import StartupSupervisor, SupervisorOutcome
from .operator_resolution import (
    CommentCorrelation,
    OverrideEvidence,
    OverrideResult,
    ResolutionEvidence,
    ResolutionResult,
    ResolutionVerdict,
    check_comment_correlation,
    force_override_unresolved,
    list_pending_submit_orders,
    resolve_pending_submit,
)

try:
    from .mt5_execution_adapter import Mt5ExecutionAdapter
except ImportError:
    pass

try:
    from .postgres_store import (
        PostgresDurableStateStore,
        PostgresPairReservationProvider,
        PostgresStartupReconciler,
    )
except ImportError:
    pass

__all__ = [
    "AMMAN_TZ",
    "AccountInfo",
    "BrokerAdapter",
    "ConnectionStatus",
    "ContractSpec",
    "DailyPnL",
    "DailyRiskConfig",
    "EntryCheck",
    "EntryDecision",
    "FOREX_CURRENCIES",
    "PairFeed",
    "RiskState",
    "SpreadConfig",
    "SpreadSnapshot",
    "SpreadTracker",
    "SymbolMapping",
    "TcpBrokerAdapter",
    "Tick",
    "TickRejectReason",
    "TickResult",
    "ZERO_PNL",
    "discover_canonical_mappings",
    "evaluate_entry",
    "evaluate_state",
    "is_new_trading_day",
    "pip_size",
    "reset_state",
    "spread_in_pips",
    "trading_day",
    # Phase 4: Strategy Engine
    "BreakoutConfig",
    "BreakoutStrategy",
    "DEFAULT_REGIME_MAP",
    "MarketRegime",
    "MeanReversionConfig",
    "MeanReversionStrategy",
    "MomentumConfig",
    "MomentumStrategy",
    "PairStrategyConfig",
    "PairStrategyEngine",
    "PricePoint",
    "RegimeConfig",
    "RegimeDetector",
    "Signal",
    "SignalDirection",
    "StrategyEngine",
    "StrategyType",
    # Phase 5: Risk and Execution
    "DurableStateStore",
    "ExecutionAdapter",
    "ExecutionAttempt",
    "ExecutionConfig",
    "ExecutionEngine",
    "FakeExecutionAdapter",
    "PairReservationProvider",
    # PostgresDurableStateStore and PostgresPairReservationProvider
    # available when psycopg is installed (import via postgres_store directly)
    "StartupReconciler",
    "StartupSupervisor",
    "SupervisorOutcome",
    "CommentCorrelation",
    "OverrideEvidence",
    "OverrideResult",
    "ResolutionEvidence",
    "ResolutionResult",
    "ResolutionVerdict",
    "check_comment_correlation",
    "force_override_unresolved",
    "list_pending_submit_orders",
    "resolve_pending_submit",
    "OrderManager",
    "OrderRecord",
    "OrderRequest",
    "OrderResult",
    "OrderSide",
    "OrderState",
    "PositionInfo",
    "PositionManager",
    "PositionState",
    "StopLossResult",
    "calculate_stop_loss",
    "is_terminal",
]
