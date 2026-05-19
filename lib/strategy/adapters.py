"""
Legacy Strategy Adapters
=========================
Wraps existing scripts (market_pulse, stage2, vcp, bottom_fisher, buying_checklist)
into the new BaseStrategy interface without modifying the original scripts.

These adapters delegate to the existing script logic while providing a unified interface
for the registry. This ensures backward compatibility — the existing pipeline and
notification system continue to work unchanged.
"""

import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from lib.strategy.base import (
    BaseStrategy,
    Signal,
    SignalType,
    StrategyLayer,
    StrategyResult,
    Urgency,
)

logger = logging.getLogger(__name__)

# Ensure project root is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _urgency_from_score(score: Optional[float], is_signal: bool) -> Urgency:
    """Derive urgency from score and signal state."""
    if not is_signal:
        return Urgency.NONE
    if score is None:
        return Urgency.LOW
    if score >= 80:
        return Urgency.HIGH
    if score >= 60:
        return Urgency.MEDIUM
    return Urgency.LOW


class MarketPulseAdapter(BaseStrategy):
    """Adapter for scripts/market_pulse.py"""

    name = "market_pulse"
    display_name = "Market Pulse"
    version = "1.0.0"
    layer = StrategyLayer.MARKET
    description = (
        "Multi-dimensional market thermometer based on IBD Distribution Day counting, "
        "index momentum, VIX regime, and market breadth analysis."
    )
    requires_market_data = True
    min_data_points = 50

    def compute(
        self, symbol: str, prices_df: pd.DataFrame,
        context: Optional[Dict[str, Any]] = None,
    ) -> StrategyResult:
        """
        Delegate to existing market_pulse logic.
        Note: Market Pulse operates on market-level data, not individual symbols.
        The 'symbol' param is typically 'SPY' or '_MARKET'.
        """
        from scripts.market_pulse import run_market_pulse

        result_data = run_market_pulse(prices_df=prices_df, context=context)

        if result_data is None:
            return StrategyResult(
                symbol=symbol,
                date=pd.Timestamp.now().strftime("%Y-%m-%d"),
                strategy=self.name,
                is_signal=False,
                summary="Market Pulse computation failed",
            )

        score = result_data.get("composite_score")
        regime = result_data.get("regime", "unknown")
        signals = []

        if regime in ("accumulation", "confirmed_uptrend"):
            signals.append(Signal(
                signal_type=SignalType.ENTRY,
                urgency=Urgency.MEDIUM,
                message=f"Market regime: {regime} (Score: {score:.1f})",
                score=score,
            ))
        elif regime in ("distribution", "downtrend"):
            signals.append(Signal(
                signal_type=SignalType.WARNING,
                urgency=Urgency.HIGH,
                message=f"Market regime: {regime} (Score: {score:.1f})",
                score=score,
            ))

        return StrategyResult(
            symbol=symbol,
            date=result_data.get("date", pd.Timestamp.now().strftime("%Y-%m-%d")),
            strategy=self.name,
            is_signal=bool(signals),
            score=score,
            passed=result_data.get("passed", 0),
            total=result_data.get("total", 0),
            conditions=result_data.get("conditions", {}),
            condition_details=result_data.get("condition_details", {}),
            metrics=result_data.get("metrics", {}),
            signals=signals,
            summary=result_data.get("summary", ""),
        )

    def get_config_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "distribution_day_threshold": {
                    "type": "integer",
                    "default": 5,
                    "description": "Number of distribution days to trigger warning",
                },
            },
        }


class Stage2Adapter(BaseStrategy):
    """Adapter for scripts/stage2_monitor.py"""

    name = "stage2"
    display_name = "Stage 2 Monitor"
    version = "1.0.0"
    layer = StrategyLayer.STOCK
    description = (
        "Stan Weinstein Stage Analysis + Minervini Trend Template. "
        "Identifies stocks in confirmed Stage 2 uptrend."
    )
    min_data_points = 200

    def compute(
        self, symbol: str, prices_df: pd.DataFrame,
        context: Optional[Dict[str, Any]] = None,
    ) -> StrategyResult:
        from scripts.stage2_monitor import analyze_stage2

        result_data = analyze_stage2(symbol, prices_df)

        if result_data is None:
            return StrategyResult(
                symbol=symbol,
                date=pd.Timestamp.now().strftime("%Y-%m-%d"),
                strategy=self.name,
                is_signal=False,
            )

        is_signal = result_data.get("is_signal", False)
        score = result_data.get("score")
        signals = []

        if is_signal:
            signals.append(Signal(
                signal_type=SignalType.ENTRY,
                urgency=_urgency_from_score(score, is_signal),
                message=result_data.get("summary", f"{symbol} in Stage 2"),
                score=score,
                position_advice=100,
            ))

        return StrategyResult(
            symbol=symbol,
            date=result_data.get("date", pd.Timestamp.now().strftime("%Y-%m-%d")),
            strategy=self.name,
            is_signal=is_signal,
            score=score,
            passed=result_data.get("passed", 0),
            total=result_data.get("total", 0),
            conditions=result_data.get("conditions", {}),
            condition_details=result_data.get("condition_details", {}),
            metrics=result_data.get("metrics", {}),
            signals=signals,
            summary=result_data.get("summary", ""),
        )


class VCPAdapter(BaseStrategy):
    """Adapter for scripts/vcp_scanner.py"""

    name = "vcp"
    display_name = "VCP Scanner"
    version = "1.0.0"
    layer = StrategyLayer.STOCK
    description = (
        "Minervini Volatility Contraction Pattern (VCP) scanner. "
        "Detects tightening price contractions ahead of breakouts."
    )
    min_data_points = 100

    def compute(
        self, symbol: str, prices_df: pd.DataFrame,
        context: Optional[Dict[str, Any]] = None,
    ) -> StrategyResult:
        from scripts.vcp_scanner import analyze_vcp

        result_data = analyze_vcp(symbol, prices_df)

        if result_data is None:
            return StrategyResult(
                symbol=symbol,
                date=pd.Timestamp.now().strftime("%Y-%m-%d"),
                strategy=self.name,
                is_signal=False,
            )

        is_signal = result_data.get("is_signal", False)
        score = result_data.get("score")
        signals = []

        if is_signal:
            signals.append(Signal(
                signal_type=SignalType.WATCH,
                urgency=_urgency_from_score(score, is_signal),
                message=result_data.get("summary", f"{symbol} VCP forming"),
                score=score,
                position_advice=50,
            ))

        return StrategyResult(
            symbol=symbol,
            date=result_data.get("date", pd.Timestamp.now().strftime("%Y-%m-%d")),
            strategy=self.name,
            is_signal=is_signal,
            score=score,
            passed=result_data.get("passed", 0),
            total=result_data.get("total", 0),
            conditions=result_data.get("conditions", {}),
            condition_details=result_data.get("condition_details", {}),
            metrics=result_data.get("metrics", {}),
            signals=signals,
            summary=result_data.get("summary", ""),
        )


class BottomFisherAdapter(BaseStrategy):
    """Adapter for scripts/bottom_fisher.py"""

    name = "bottom_fisher"
    display_name = "Bottom Fisher"
    version = "1.0.0"
    layer = StrategyLayer.STOCK
    description = (
        "Mean-reversion based bottom-fishing with multi-layer progressive signals. "
        "Identifies oversold conditions with reversal confirmation."
    )
    min_data_points = 100

    def compute(
        self, symbol: str, prices_df: pd.DataFrame,
        context: Optional[Dict[str, Any]] = None,
    ) -> StrategyResult:
        from scripts.bottom_fisher import analyze_bottom

        result_data = analyze_bottom(symbol, prices_df)

        if result_data is None:
            return StrategyResult(
                symbol=symbol,
                date=pd.Timestamp.now().strftime("%Y-%m-%d"),
                strategy=self.name,
                is_signal=False,
            )

        is_signal = result_data.get("is_signal", False)
        score = result_data.get("score")
        signals = []

        if is_signal:
            signals.append(Signal(
                signal_type=SignalType.ENTRY,
                urgency=_urgency_from_score(score, is_signal),
                message=result_data.get("summary", f"{symbol} bottom signal"),
                score=score,
                position_advice=30,
            ))

        return StrategyResult(
            symbol=symbol,
            date=result_data.get("date", pd.Timestamp.now().strftime("%Y-%m-%d")),
            strategy=self.name,
            is_signal=is_signal,
            score=score,
            passed=result_data.get("passed", 0),
            total=result_data.get("total", 0),
            conditions=result_data.get("conditions", {}),
            condition_details=result_data.get("condition_details", {}),
            metrics=result_data.get("metrics", {}),
            signals=signals,
            summary=result_data.get("summary", ""),
        )


class BuyingChecklistAdapter(BaseStrategy):
    """Adapter for scripts/buying_checklist.py"""

    name = "buying_checklist"
    display_name = "Buying Checklist"
    version = "1.0.0"
    layer = StrategyLayer.STOCK
    description = (
        "Elder Impulse + multi-dimensional composite confirmation checklist. "
        "Final buy/no-buy decision integrating all factors."
    )
    requires_market_data = True
    min_data_points = 100

    def compute(
        self, symbol: str, prices_df: pd.DataFrame,
        context: Optional[Dict[str, Any]] = None,
    ) -> StrategyResult:
        from scripts.buying_checklist import analyze_checklist

        result_data = analyze_checklist(symbol, prices_df, context=context)

        if result_data is None:
            return StrategyResult(
                symbol=symbol,
                date=pd.Timestamp.now().strftime("%Y-%m-%d"),
                strategy=self.name,
                is_signal=False,
            )

        is_signal = result_data.get("is_signal", False)
        score = result_data.get("score")
        signals = []

        if is_signal:
            signals.append(Signal(
                signal_type=SignalType.ENTRY,
                urgency=Urgency.HIGH if score and score >= 80 else Urgency.MEDIUM,
                message=result_data.get("summary", f"{symbol} buy checklist passed"),
                score=score,
                position_advice=100,
            ))

        return StrategyResult(
            symbol=symbol,
            date=result_data.get("date", pd.Timestamp.now().strftime("%Y-%m-%d")),
            strategy=self.name,
            is_signal=is_signal,
            score=score,
            passed=result_data.get("passed", 0),
            total=result_data.get("total", 0),
            conditions=result_data.get("conditions", {}),
            condition_details=result_data.get("condition_details", {}),
            metrics=result_data.get("metrics", {}),
            signals=signals,
            summary=result_data.get("summary", ""),
        )
