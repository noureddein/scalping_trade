from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
import re


FIXED_LOT_SIZE = Decimal("0.01")
# Intended per-trade loss ceiling, not a guaranteed maximum. Gaps,
# slippage, and execution failures may cause actual losses to exceed this.
MAX_INTENDED_LOSS_USD = Decimal("0.50")
REQUIRED_SPREAD_STABILITY_SECONDS = Decimal("60")
_CANONICAL_PAIR = re.compile(r"^[A-Z]{6}$")
_NON_FOREX_BASES = frozenset({"XAU", "XAG", "XPT", "XPD"})

# Explicitly supported forex currencies. Fail-closed: any three-letter code
# NOT in this set is rejected as a canonical currency.
#
# This is an explicitly maintained subset, not the complete universe of valid
# forex currencies. All entries are ISO 4217 codes except where noted.
# Broker availability has NOT been verified — the list is curated from
# currencies that typically appear on retail forex platforms.
#
# To add a currency:
#   1. Confirm it has an ISO 4217 code (or document the exception below).
#   2. Add it here and to the tests in test_broker_adapter.py.
#   3. If it is a non-ISO market convention (like CNH), add it to
#      _BROKER_CONVENTION_CURRENCIES below instead, with documentation.
#
# Non-ISO broker conventions are handled separately so that ISO 4217
# compliance of the main set is machine-auditable.

# ISO 4217 fiat currency codes.
_ISO_FOREX_CURRENCIES = frozenset({
    "AED", "ARS", "AUD", "BGN", "BHD", "BRL", "CAD", "CHF", "CLP",
    "CNY", "COP", "CZK", "DKK", "EGP", "EUR", "GBP", "HKD",
    "HRK", "HUF", "IDR", "ILS", "INR", "ISK", "JOD", "JPY", "KES",
    "KRW", "KWD", "MXN", "MYR", "NGN", "NOK", "NZD", "OMR", "PEN",
    "PHP", "PKR", "PLN", "QAR", "RON", "RUB", "SAR", "SEK", "SGD",
    "THB", "TND", "TRY", "TWD", "UAH", "UGX", "USD", "UYU", "VND",
    "ZAR", "ZMW",
})

# Non-ISO codes that are standard broker conventions for forex trading.
# CNH: offshore Chinese yuan, universally used on MT5 brokers for yuan
# forex pairs. ISO 4217 only defines CNY (onshore). CNH is not an ISO
# code but is the de-facto standard for offshore yuan trading.
_BROKER_CONVENTION_CURRENCIES = frozenset({
    "CNH",
})

FOREX_CURRENCIES = _ISO_FOREX_CURRENCIES | _BROKER_CONVENTION_CURRENCIES


def _is_finite_decimal(value: object) -> bool:
    return isinstance(value, Decimal) and value.is_finite()


class RiskState(str, Enum):
    ACTIVE = "ACTIVE"
    PROFIT_LOCKED = "PROFIT_LOCKED"
    LOSS_LOCKED = "LOSS_LOCKED"
    DRAINING = "DRAINING"
    DISABLED = "DISABLED"


@dataclass(frozen=True, slots=True)
class EntryCheck:
    canonical_pair: str
    volume_lots: Decimal
    risk_state: RiskState | None
    backend_available: bool
    broker_connected: bool
    risk_state_age_seconds: Decimal | None
    max_risk_state_age_seconds: Decimal
    market_data_fresh: bool
    trading_enabled: bool
    manual_spread_ok: bool
    adaptive_spread_ok: bool
    stable_spread_seconds: Decimal
    has_open_position: bool
    has_pending_entry: bool
    estimated_loss_usd: Decimal | None
    loss_estimate_valid: bool
    spread_gate_eligible: bool = True


@dataclass(frozen=True, slots=True)
class EntryDecision:
    approved: bool
    reasons: tuple[str, ...]


def _canonical_pair_error(pair: str) -> str | None:
    if not _CANONICAL_PAIR.fullmatch(pair):
        return "canonical_pair_must_be_six_uppercase_letters"
    base, quote = pair[:3], pair[3:]
    if base in _NON_FOREX_BASES or quote in _NON_FOREX_BASES:
        return "non_forex_instrument"
    if base == quote:
        return "base_and_quote_currency_must_differ"
    if base not in FOREX_CURRENCIES or quote not in FOREX_CURRENCIES:
        return "unknown_currency_not_in_forex_whitelist"
    return None


def evaluate_entry(check: EntryCheck) -> EntryDecision:
    """Apply fixed, approved safety constraints without performing a trade.

    Missing or stale authority, market data, spread state, or risk estimates
    deny the entry.  Non-finite numeric inputs (NaN, Infinity) deny
    fail-closed rather than relying on comparison semantics.
    """
    reasons: list[str] = []

    pair_error = _canonical_pair_error(check.canonical_pair)
    if pair_error:
        reasons.append(pair_error)

    if not _is_finite_decimal(check.volume_lots):
        reasons.append("volume_must_equal_fixed_0_01_lot")
    elif check.volume_lots != FIXED_LOT_SIZE:
        reasons.append("volume_must_equal_fixed_0_01_lot")

    if not check.backend_available:
        reasons.append("risk_authority_unavailable")

    if not check.broker_connected:
        reasons.append("broker_not_connected")

    if check.risk_state is None:
        reasons.append("risk_state_unavailable")
    elif check.risk_state is not RiskState.ACTIVE:
        reasons.append("risk_state_not_active")

    if check.risk_state_age_seconds is None:
        reasons.append("risk_state_age_unknown")
    elif not _is_finite_decimal(check.risk_state_age_seconds):
        reasons.append("risk_state_age_invalid")
    elif not _is_finite_decimal(check.max_risk_state_age_seconds):
        reasons.append("risk_state_max_age_invalid")
    elif check.risk_state_age_seconds < 0:
        reasons.append("risk_state_age_invalid")
    elif check.max_risk_state_age_seconds < 0:
        reasons.append("risk_state_max_age_invalid")
    elif check.risk_state_age_seconds > check.max_risk_state_age_seconds:
        reasons.append("risk_state_stale")

    if not check.market_data_fresh:
        reasons.append("market_data_stale")

    if not check.trading_enabled:
        reasons.append("pair_trading_disabled")

    if not check.manual_spread_ok:
        reasons.append("manual_spread_limit_exceeded")

    if not check.adaptive_spread_ok:
        reasons.append("adaptive_spread_limit_exceeded")

    if not check.spread_gate_eligible:
        reasons.append("spread_gate_unconfigured_or_market_unhealthy")

    if not _is_finite_decimal(check.stable_spread_seconds):
        reasons.append("spread_not_stable_for_required_60_seconds")
    elif check.stable_spread_seconds < REQUIRED_SPREAD_STABILITY_SECONDS:
        reasons.append("spread_not_stable_for_required_60_seconds")

    if check.has_open_position:
        reasons.append("canonical_pair_already_has_open_position")

    if check.has_pending_entry:
        reasons.append("canonical_pair_already_has_pending_entry")

    if not check.loss_estimate_valid or check.estimated_loss_usd is None:
        reasons.append("usd_loss_estimate_unavailable_or_invalid")
    elif not _is_finite_decimal(check.estimated_loss_usd):
        reasons.append("usd_loss_estimate_unavailable_or_invalid")
    elif check.estimated_loss_usd < 0:
        reasons.append("usd_loss_estimate_invalid")
    elif check.estimated_loss_usd > MAX_INTENDED_LOSS_USD:
        reasons.append("estimated_loss_exceeds_intended_0_50_usd_loss_ceiling")

    return EntryDecision(approved=not reasons, reasons=tuple(reasons))
