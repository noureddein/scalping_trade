"""Forward test report generation (Phase 8).

Generates ForwardTestReport with mandatory statistical limitations
and disclaimers. Never claims positive expectancy without documented
statistical evidence. Never authorizes live trading.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class ForwardTestReport:
    report_id: uuid.UUID
    session_id: uuid.UUID
    sample_size: int
    sample_sufficient: bool
    net_pnl: Decimal
    gross_pnl: Decimal
    total_spread_cost: Decimal
    total_commission: Decimal
    total_swap: Decimal
    avg_slippage_pips: Decimal
    max_drawdown: Decimal
    win_rate: Decimal
    avg_trade_duration: timedelta
    statistical_warnings: list[str]
    generated_at: datetime


_MANDATORY_DISCLAIMER = "These results do not authorize live trading."
_INSUFFICIENT_SAMPLE = "Insufficient sample size for statistical inference."


def generate_report(
    *,
    session_id: uuid.UUID,
    trades: list[dict[str, Any]],
    discrepancies: list[dict[str, Any]],
    sample_threshold: int | None = None,
) -> ForwardTestReport:
    """Generate a ForwardTestReport from trade and discrepancy data.

    trades: list of dicts with keys: pnl, gross_pnl, spread_cost, commission,
            swap, duration_seconds, is_win
    discrepancies: list of dicts with key: slippage_pips
    sample_threshold: owner-defined minimum sample size (None = no threshold)
    """
    sample_size = len(trades)
    sample_sufficient = (
        sample_threshold is not None and sample_size >= sample_threshold
    )

    if sample_size == 0:
        return ForwardTestReport(
            report_id=uuid.uuid4(),
            session_id=session_id,
            sample_size=0,
            sample_sufficient=False,
            net_pnl=Decimal("0"),
            gross_pnl=Decimal("0"),
            total_spread_cost=Decimal("0"),
            total_commission=Decimal("0"),
            total_swap=Decimal("0"),
            avg_slippage_pips=Decimal("0"),
            max_drawdown=Decimal("0"),
            win_rate=Decimal("0"),
            avg_trade_duration=timedelta(0),
            statistical_warnings=[_MANDATORY_DISCLAIMER, _INSUFFICIENT_SAMPLE],
            generated_at=datetime.now(timezone.utc),
        )

    net_pnl = sum((Decimal(str(t["pnl"])) for t in trades), Decimal("0"))
    gross_pnl = sum((Decimal(str(t["gross_pnl"])) for t in trades), Decimal("0"))
    total_spread = sum((Decimal(str(t["spread_cost"])) for t in trades), Decimal("0"))
    total_commission = sum((Decimal(str(t["commission"])) for t in trades), Decimal("0"))
    total_swap = sum((Decimal(str(t["swap"])) for t in trades), Decimal("0"))

    wins = sum(1 for t in trades if t.get("is_win"))
    win_rate = Decimal(str(wins)) / Decimal(str(sample_size)) * Decimal("100")

    total_duration = sum((t.get("duration_seconds", 0) for t in trades), 0)
    avg_duration = timedelta(seconds=total_duration / sample_size)

    max_drawdown = _compute_max_drawdown(trades)

    if discrepancies:
        total_slippage = sum(
            (Decimal(str(d["slippage_pips"])) for d in discrepancies), Decimal("0")
        )
        avg_slippage = total_slippage / Decimal(str(len(discrepancies)))
    else:
        avg_slippage = Decimal("0")

    warnings: list[str] = [_MANDATORY_DISCLAIMER]
    if not sample_sufficient:
        warnings.append(_INSUFFICIENT_SAMPLE)

    return ForwardTestReport(
        report_id=uuid.uuid4(),
        session_id=session_id,
        sample_size=sample_size,
        sample_sufficient=sample_sufficient,
        net_pnl=net_pnl,
        gross_pnl=gross_pnl,
        total_spread_cost=total_spread,
        total_commission=total_commission,
        total_swap=total_swap,
        avg_slippage_pips=avg_slippage,
        max_drawdown=max_drawdown,
        win_rate=win_rate,
        avg_trade_duration=avg_duration,
        statistical_warnings=warnings,
        generated_at=datetime.now(timezone.utc),
    )


def _compute_max_drawdown(trades: list[dict[str, Any]]) -> Decimal:
    """Compute maximum drawdown from sequential P/L."""
    if not trades:
        return Decimal("0")
    equity = Decimal("0")
    peak = Decimal("0")
    max_dd = Decimal("0")
    for t in trades:
        equity += Decimal(str(t["pnl"]))
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd
    return max_dd
