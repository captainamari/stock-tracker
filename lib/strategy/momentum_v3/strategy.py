"""
Momentum V3 Strategy — Main Plugin Class
==========================================
Integrates core computation + V3 signal engine into the BaseStrategy interface.

Supports three operational modes:
    - Stock mode (default): Computes momentum for individual stocks
    - Sector mode: Computes momentum for sector ETFs + relative strength
    - Market mode: Computes momentum for SPY/QQQ market sentiment

The strategy produces:
    - Composite Momentum Score (0-100)
    - V3 Entry/Exit/Hold signals
    - Relative strength vs sector and market
    - Position sizing recommendations
"""

import logging
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
from lib.strategy.momentum_v3.core import (
    compute_composite_momentum_v2,
    compute_full_momentum,
    get_regime,
)
from lib.strategy.momentum_v3.signals import V3SignalEngine

logger = logging.getLogger(__name__)


# Default sector configuration
DEFAULT_SECTORS = {
    "semiconductors": {
        "etf": "SMH",
        "name": "Semiconductors/Storage",
        "decision_priority": "sector_first",
    },
    "defense": {
        "etf": "ITA",
        "name": "Defense/Drones",
        "decision_priority": "stock_first",
    },
    "software": {
        "etf": "IGV",
        "name": "Software/SaaS",
        "decision_priority": "stock_first",
    },
    "biotech": {
        "etf": "XBI",
        "name": "AI Healthcare/Biotech",
        "decision_priority": "stock_first",
    },
    "optical": {
        "etf": "BASKET",
        "basket_tickers": ["COHR", "LITE", "ANET"],
        "name": "Optical Modules",
        "decision_priority": "sector_first",
    },
}

# Default stock-to-sector mapping
DEFAULT_STOCK_SECTORS = {
    "NVDA": "semiconductors",
    "TSLA": None,
    "ZETA": "software",
    "TEM": "biotech",
    "RCAT": "defense",
}


def _normalize_prices_df(prices_df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalize a prices DataFrame to have lowercase columns and a 'date' column.

    Handles:
    - Capitalized columns (Close -> close, Open -> open, etc.)
    - Date in index vs date as column
    - Datetime objects converted to string dates
    """
    df = prices_df.copy()

    # Lowercase all columns
    df.columns = [c.lower() for c in df.columns]

    # Handle date: might be index or column
    if "date" not in df.columns:
        if df.index.name and df.index.name.lower() == "date":
            df = df.reset_index()
            df.columns = [c.lower() for c in df.columns]
        elif hasattr(df.index, 'strftime'):
            # DatetimeIndex without name
            df["date"] = df.index.strftime("%Y-%m-%d")
            df = df.reset_index(drop=True)
        else:
            # Use index as date
            df["date"] = [str(x) for x in df.index]
            df = df.reset_index(drop=True)

    # Ensure date is string format
    if "date" in df.columns:
        if hasattr(df["date"].iloc[0], 'strftime'):
            df["date"] = df["date"].apply(lambda x: x.strftime("%Y-%m-%d") if hasattr(x, 'strftime') else str(x))
        else:
            df["date"] = df["date"].astype(str).str[:10]  # Trim any time part

    return df


class MomentumV3Strategy(BaseStrategy):
    """
    Multi-layer Momentum Dashboard V3 strategy.

    Computes Composite Momentum Score and generates V3 trading signals
    with entry confirmation, graduated exit, and false breakout filtering.
    """

    name = "momentum_v3"
    display_name = "Momentum V3"
    version = "3.0.0"
    layer = StrategyLayer.STOCK
    description = (
        "Three-layer momentum analysis (Market → Sector → Stock) with "
        "V3 entry/exit rules, relative strength, and position sizing."
    )
    requires_market_data = True
    requires_sector_data = True
    min_data_points = 30

    def __init__(self):
        self.sectors = DEFAULT_SECTORS
        self.stock_sectors = DEFAULT_STOCK_SECTORS

    def compute(
        self,
        symbol: str,
        prices_df: pd.DataFrame,
        context: Optional[Dict[str, Any]] = None,
    ) -> StrategyResult:
        """
        Compute Momentum V3 for a single symbol.

        Context can provide:
            - market_scores: {ticker: score} for SPY/QQQ (for relative strength)
            - sector_scores: {sector_name: score} for sector comparison
            - config: {"sectors": {...}, "stock_sectors": {...}}
        """
        context = context or {}

        # Normalize DataFrame (handle capitalized cols, date in index, etc.)
        prices_df = _normalize_prices_df(prices_df)

        # Extract closes and dates from DataFrame
        if "close" not in prices_df.columns:
            return self._empty_result(symbol, "Missing 'close' column")

        closes = prices_df["close"].tolist()
        dates = prices_df["date"].astype(str).tolist() if "date" in prices_df.columns else [
            str(i) for i in range(len(closes))
        ]

        # Compute momentum
        final_scores, raw_scores = compute_composite_momentum_v2(closes)

        if all(s is None for s in final_scores):
            return self._empty_result(symbol, "Insufficient data for momentum computation")

        # Run V3 Signal Engine
        engine = V3SignalEngine(final_scores, dates, closes)
        v3_signal = engine.analyze()

        # Compute relative strength
        relative_strength = self._compute_relative_strength(
            symbol, v3_signal.current_score, context
        )

        # Build trading signals
        signals = self._build_signals(v3_signal, relative_strength)

        # Latest price info
        latest_price = closes[-1]
        prev_price = closes[-2] if len(closes) > 1 else closes[-1]
        daily_change_pct = (latest_price - prev_price) / prev_price * 100

        # Build conditions dict
        conditions = {}
        if v3_signal.current_score is not None:
            conditions["score_above_70"] = v3_signal.current_score >= 70
            conditions["score_above_65"] = v3_signal.current_score >= 65
            conditions["score_above_60"] = v3_signal.current_score >= 60
            conditions["score_above_40"] = v3_signal.current_score >= 40
            conditions["consecutive_65_3d"] = v3_signal.consecutive_above_65 >= 3
            conditions["no_false_breakout"] = (
                v3_signal.score_5d_change is not None and v3_signal.score_5d_change >= 5
            )

        passed = sum(1 for v in conditions.values() if v)
        total = len(conditions)

        # Determine if actionable signal
        is_signal = v3_signal.urgency in ("CRITICAL", "HIGH", "MEDIUM")

        # Metrics
        metrics = {
            "current_score": v3_signal.current_score,
            "regime": v3_signal.regime,
            "delta_1d": v3_signal.delta_1d,
            "score_5d_change": v3_signal.score_5d_change,
            "consecutive_above_65": v3_signal.consecutive_above_65,
            "consecutive_above_70": v3_signal.consecutive_above_70,
            "consecutive_below_60": v3_signal.consecutive_below_60,
            "consecutive_decline": v3_signal.consecutive_decline,
            "position_advice": v3_signal.position_advice,
            "price": latest_price,
            "daily_change_pct": round(daily_change_pct, 2),
            "relative_strength": relative_strength,
            # Score history (last 20 days for charting)
            "score_history": [
                {"date": dates[i], "score": final_scores[i]}
                for i in range(max(0, len(dates) - 20), len(dates))
                if final_scores[i] is not None
            ],
        }

        # Summary
        summary_parts = [f"Score={v3_signal.current_score:.1f}" if v3_signal.current_score else "N/A"]
        summary_parts.append(v3_signal.regime)
        if v3_signal.position_advice is not None:
            summary_parts.append(f"Position:{v3_signal.position_advice}%")
        summary = " | ".join(summary_parts)

        return StrategyResult(
            symbol=symbol,
            date=dates[-1] if dates else "",
            strategy=self.name,
            is_signal=is_signal,
            score=v3_signal.current_score,
            passed=passed,
            total=total,
            conditions=conditions,
            condition_details={
                "v3_signals": v3_signal.signals,
                "urgency": v3_signal.urgency,
            },
            metrics=metrics,
            signals=signals,
            summary=summary,
        )

    def _compute_relative_strength(
        self,
        symbol: str,
        current_score: Optional[float],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Compute relative strength vs market and sector."""
        rs = {"vs_spy": None, "vs_sector": None, "sector_name": None, "alpha": None}

        if current_score is None:
            return rs

        # vs SPY (market)
        market_scores = context.get("market_scores", {})
        spy_score = market_scores.get("SPY")
        if spy_score is not None:
            rs["vs_spy"] = round(current_score - spy_score, 1)

        # vs Sector
        sector_scores = context.get("sector_scores", {})
        sector_key = self.stock_sectors.get(symbol)
        if sector_key and sector_key in sector_scores:
            sector_score = sector_scores[sector_key]
            rs["sector_name"] = self.sectors.get(sector_key, {}).get("name", sector_key)
            rs["vs_sector"] = round(current_score - sector_score, 1)
            # Alpha: stock outperforms sector
            rs["alpha"] = rs["vs_sector"] > 5

        return rs

    def _build_signals(
        self,
        v3_signal,
        relative_strength: Dict[str, Any],
    ) -> List[Signal]:
        """Convert V3Signal to list of standard Signal objects."""
        signals = []

        if v3_signal.current_score is None:
            return signals

        # Map V3 urgency to our Urgency enum
        urgency_map = {
            "CRITICAL": Urgency.CRITICAL,
            "HIGH": Urgency.HIGH,
            "MEDIUM": Urgency.MEDIUM,
            "LOW": Urgency.LOW,
            "NONE": Urgency.NONE,
        }
        urgency = urgency_map.get(v3_signal.urgency, Urgency.NONE)

        # Determine signal type from regime/signals
        if v3_signal.urgency in ("CRITICAL",) and v3_signal.position_advice == 0:
            signal_type = SignalType.EXIT
        elif v3_signal.urgency in ("CRITICAL", "HIGH") and v3_signal.position_advice is not None and v3_signal.position_advice <= 30:
            signal_type = SignalType.SCALE_OUT
        elif v3_signal.regime == "STRONG_TREND" and v3_signal.consecutive_above_70 <= 2:
            signal_type = SignalType.ENTRY
        elif v3_signal.position_advice == 100 and v3_signal.consecutive_above_65 >= 3:
            signal_type = SignalType.SCALE_IN
        elif v3_signal.regime in ("STRONG_TREND", "STRONG"):
            signal_type = SignalType.HOLD
        elif v3_signal.regime == "NEUTRAL":
            signal_type = SignalType.WATCH
        else:
            signal_type = SignalType.WARNING if urgency != Urgency.NONE else SignalType.NONE

        # Primary signal
        primary_msg = v3_signal.signals[0] if v3_signal.signals else f"Score={v3_signal.current_score:.1f}"
        signals.append(Signal(
            signal_type=signal_type,
            urgency=urgency,
            message=primary_msg,
            position_advice=v3_signal.position_advice,
            score=v3_signal.current_score,
            details={
                "all_signals": v3_signal.signals,
                "delta_1d": v3_signal.delta_1d,
                "score_5d_change": v3_signal.score_5d_change,
                "relative_strength": relative_strength,
            },
        ))

        # Additional warning signals
        for msg in v3_signal.signals[1:]:
            if "⚠️" in msg or "⚡" in msg or "🛑" in msg:
                signals.append(Signal(
                    signal_type=SignalType.WARNING,
                    urgency=Urgency.HIGH if "🛑" in msg else Urgency.MEDIUM,
                    message=msg,
                    score=v3_signal.current_score,
                ))

        return signals

    def _empty_result(self, symbol: str, reason: str) -> StrategyResult:
        """Return empty result for error cases."""
        return StrategyResult(
            symbol=symbol,
            date="",
            strategy=self.name,
            is_signal=False,
            summary=reason,
        )

    def get_config_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "sectors": {
                    "type": "object",
                    "description": "Sector ETF configuration",
                },
                "stock_sectors": {
                    "type": "object",
                    "description": "Stock-to-sector mapping",
                },
                "entry_score_threshold": {
                    "type": "number",
                    "default": 70,
                    "description": "Level 1 entry score threshold",
                },
                "exit_score_threshold": {
                    "type": "number",
                    "default": 60,
                    "description": "Red exit score threshold",
                },
                "full_sell_threshold": {
                    "type": "number",
                    "default": 50,
                    "description": "Full sell score threshold",
                },
            },
        }


class SectorMomentumStrategy(BaseStrategy):
    """
    Sector-level Momentum V3 (Layer 1).

    Computes momentum for sector ETFs and provides the sector context
    needed by individual stock momentum analysis.
    """

    name = "sector_momentum"
    display_name = "Sector Momentum"
    version = "3.0.0"
    layer = StrategyLayer.SECTOR
    description = (
        "Sector ETF momentum analysis. Provides sector-level signals "
        "and context for stock relative strength calculations."
    )
    min_data_points = 30

    def compute(
        self,
        symbol: str,
        prices_df: pd.DataFrame,
        context: Optional[Dict[str, Any]] = None,
    ) -> StrategyResult:
        """Compute momentum for a sector ETF."""
        prices_df = _normalize_prices_df(prices_df)

        if "close" not in prices_df.columns:
            return StrategyResult(
                symbol=symbol, date="", strategy=self.name, is_signal=False,
                summary="Missing 'close' column",
            )

        closes = prices_df["close"].tolist()
        dates = prices_df["date"].astype(str).tolist() if "date" in prices_df.columns else []

        final_scores, _ = compute_composite_momentum_v2(closes)

        if all(s is None for s in final_scores):
            return StrategyResult(
                symbol=symbol, date="", strategy=self.name, is_signal=False,
                summary="Insufficient data",
            )

        engine = V3SignalEngine(final_scores, dates, closes)
        v3_signal = engine.analyze()

        # Map to standard signals
        urgency_map = {
            "CRITICAL": Urgency.CRITICAL, "HIGH": Urgency.HIGH,
            "MEDIUM": Urgency.MEDIUM, "LOW": Urgency.LOW, "NONE": Urgency.NONE,
        }
        urgency = urgency_map.get(v3_signal.urgency, Urgency.NONE)

        signals = []
        if v3_signal.urgency != "NONE":
            signals.append(Signal(
                signal_type=SignalType.WARNING if v3_signal.position_advice and v3_signal.position_advice < 50 else SignalType.HOLD,
                urgency=urgency,
                message=v3_signal.signals[0] if v3_signal.signals else "",
                position_advice=v3_signal.position_advice,
                score=v3_signal.current_score,
            ))

        is_signal = v3_signal.urgency in ("CRITICAL", "HIGH", "MEDIUM")

        return StrategyResult(
            symbol=symbol,
            date=dates[-1] if dates else "",
            strategy=self.name,
            is_signal=is_signal,
            score=v3_signal.current_score,
            metrics={
                "regime": v3_signal.regime,
                "delta_1d": v3_signal.delta_1d,
                "score_5d_change": v3_signal.score_5d_change,
                "position_advice": v3_signal.position_advice,
                "score_history": [
                    {"date": dates[i], "score": final_scores[i]}
                    for i in range(max(0, len(dates) - 20), len(dates))
                    if i < len(final_scores) and final_scores[i] is not None
                ],
            },
            signals=signals,
            summary=f"{v3_signal.regime} Score={v3_signal.current_score:.1f}" if v3_signal.current_score else "N/A",
        )


class MarketSentimentStrategy(BaseStrategy):
    """
    Market Sentiment Momentum (Layer 0).

    Analyzes SPY/QQQ momentum to determine overall market Risk-on/Risk-off state.
    """

    name = "market_sentiment"
    display_name = "Market Sentiment"
    version = "3.0.0"
    layer = StrategyLayer.MARKET
    description = (
        "Market-level momentum analysis using SPY/QQQ. "
        "Determines Risk-on/Risk-off market state as reference for stock decisions."
    )
    min_data_points = 30

    def compute(
        self,
        symbol: str,
        prices_df: pd.DataFrame,
        context: Optional[Dict[str, Any]] = None,
    ) -> StrategyResult:
        """Compute market sentiment momentum."""
        prices_df = _normalize_prices_df(prices_df)

        if "close" not in prices_df.columns:
            return StrategyResult(
                symbol=symbol, date="", strategy=self.name, is_signal=False,
            )

        closes = prices_df["close"].tolist()
        dates = prices_df["date"].astype(str).tolist() if "date" in prices_df.columns else []

        final_scores, _ = compute_composite_momentum_v2(closes)

        if all(s is None for s in final_scores):
            return StrategyResult(
                symbol=symbol, date="", strategy=self.name, is_signal=False,
            )

        engine = V3SignalEngine(final_scores, dates, closes)
        v3_signal = engine.analyze()

        # Determine market mood
        score = v3_signal.current_score
        if score is not None:
            if score >= 70:
                mood = "RISK-ON (Full market strength)"
            elif score >= 60:
                mood = "RISK-ON leaning"
            elif score >= 40:
                mood = "NEUTRAL"
            else:
                mood = "RISK-OFF (Defensive mode)"
        else:
            mood = "N/A"

        signals = []
        if score is not None and score < 40:
            signals.append(Signal(
                signal_type=SignalType.WARNING,
                urgency=Urgency.HIGH,
                message=f"Market RISK-OFF: {symbol} Score={score:.1f}",
                score=score,
            ))
        elif score is not None and score >= 70:
            signals.append(Signal(
                signal_type=SignalType.HOLD,
                urgency=Urgency.LOW,
                message=f"Market RISK-ON: {symbol} Score={score:.1f}",
                score=score,
            ))

        return StrategyResult(
            symbol=symbol,
            date=dates[-1] if dates else "",
            strategy=self.name,
            is_signal=bool(signals),
            score=score,
            metrics={
                "regime": v3_signal.regime,
                "mood": mood,
                "delta_1d": v3_signal.delta_1d,
                "score_5d_change": v3_signal.score_5d_change,
                "score_history": [
                    {"date": dates[i], "score": final_scores[i]}
                    for i in range(max(0, len(dates) - 20), len(dates))
                    if i < len(final_scores) and final_scores[i] is not None
                ],
            },
            signals=signals,
            summary=f"{mood} | Score={score:.1f}" if score else "N/A",
        )
