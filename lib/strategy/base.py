"""
Base Strategy Interface
========================
All strategies must inherit from BaseStrategy and implement the required methods.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

import pandas as pd


class StrategyLayer(str, Enum):
    """Strategy operates at which level of the market hierarchy."""
    MARKET = "market"      # Market-wide indicators (SPY, VIX, breadth)
    SECTOR = "sector"      # Sector/ETF level
    STOCK = "stock"        # Individual stock level


class SignalType(str, Enum):
    """Type of trading signal."""
    ENTRY = "entry"            # New position entry
    EXIT = "exit"              # Full exit
    SCALE_IN = "scale_in"     # Add to position
    SCALE_OUT = "scale_out"   # Partial exit
    HOLD = "hold"             # Maintain position
    WATCH = "watch"           # On watchlist, not actionable yet
    WARNING = "warning"       # Risk alert
    NONE = "none"             # No signal


class Urgency(str, Enum):
    """Signal urgency level for UI prioritization."""
    CRITICAL = "critical"   # Act immediately (e.g., stop loss triggered)
    HIGH = "high"           # Act today
    MEDIUM = "medium"       # Act within 1-2 days
    LOW = "low"             # Informational
    NONE = "none"           # No action needed


@dataclass
class Signal:
    """A trading signal produced by a strategy."""
    signal_type: SignalType
    urgency: Urgency
    message: str                          # Human-readable signal description
    position_advice: Optional[int] = None # Suggested position size (0-100%)
    score: Optional[float] = None         # Strategy-specific score
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "signal_type": self.signal_type.value,
            "urgency": self.urgency.value,
            "message": self.message,
            "position_advice": self.position_advice,
            "score": self.score,
            "details": self.details,
        }


@dataclass
class StrategyResult:
    """Complete result of running a strategy on a symbol."""
    symbol: str
    date: str                              # Analysis date (YYYY-MM-DD)
    strategy: str                          # Strategy name identifier
    is_signal: bool                        # Whether an actionable signal exists
    score: Optional[float] = None          # Overall score (0-100)
    passed: int = 0                        # Conditions passed
    total: int = 0                         # Total conditions
    conditions: Dict[str, bool] = field(default_factory=dict)
    condition_details: Dict[str, Any] = field(default_factory=dict)
    metrics: Dict[str, Any] = field(default_factory=dict)
    signals: List[Signal] = field(default_factory=list)
    summary: str = ""

    @property
    def primary_signal(self) -> Optional[Signal]:
        """Get the highest-urgency signal."""
        if not self.signals:
            return None
        urgency_order = {
            Urgency.CRITICAL: 0, Urgency.HIGH: 1,
            Urgency.MEDIUM: 2, Urgency.LOW: 3, Urgency.NONE: 4,
        }
        return min(self.signals, key=lambda s: urgency_order.get(s.urgency, 9))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "date": self.date,
            "strategy": self.strategy,
            "is_signal": self.is_signal,
            "score": self.score,
            "passed": self.passed,
            "total": self.total,
            "conditions": self.conditions,
            "condition_details": self.condition_details,
            "metrics": self.metrics,
            "signals": [s.to_dict() for s in self.signals],
            "summary": self.summary,
        }

    def to_db_dict(self) -> Dict[str, Any]:
        """Convert to format compatible with lib.db.save_strategy_result."""
        return {
            "symbol": self.symbol,
            "date": self.date,
            "strategy": self.strategy,
            "is_signal": self.is_signal,
            "score": self.score,
            "passed": self.passed,
            "total": self.total,
            "conditions": self.conditions,
            "condition_details": self.condition_details,
            "metrics": self.metrics,
            "summary": self.summary,
        }


class BaseStrategy(ABC):
    """
    Abstract base class for all trading strategies.

    Subclasses must define class-level attributes and implement compute/get_signals.

    Example:
        class MomentumV3(BaseStrategy):
            name = "momentum_v3"
            display_name = "Momentum V3"
            version = "3.0.0"
            layer = StrategyLayer.STOCK

            def compute(self, symbol, prices_df):
                ...
                return StrategyResult(...)

            def get_signals(self, result):
                ...
                return [Signal(...)]
    """

    # --- Class attributes (must be overridden) ---
    name: str = ""                          # Unique identifier (snake_case)
    display_name: str = ""                  # Human-readable name
    version: str = "1.0.0"                  # Semantic version
    layer: StrategyLayer = StrategyLayer.STOCK
    description: str = ""                   # Brief description

    # --- Optional configuration ---
    default_config: Dict[str, Any] = {}     # Default parameters
    requires_market_data: bool = False      # Needs SPY/QQQ/VIX etc.
    requires_sector_data: bool = False      # Needs sector ETF data
    min_data_points: int = 50               # Minimum price bars needed

    @abstractmethod
    def compute(self, symbol: str, prices_df: pd.DataFrame,
                context: Optional[Dict[str, Any]] = None) -> StrategyResult:
        """
        Run strategy computation on a single symbol.

        Args:
            symbol: Ticker symbol (e.g., "NVDA")
            prices_df: DataFrame with columns [date, open, high, low, close, volume]
                       sorted by date ascending. Index is integer.
            context: Optional dict with additional data:
                     - market_data: {ticker: prices_df} for SPY/QQQ etc.
                     - sector_data: {sector_name: prices_df} for ETFs
                     - config: strategy-specific config overrides

        Returns:
            StrategyResult with computed metrics and signals.
        """
        ...

    def get_signals(self, result: StrategyResult) -> List[Signal]:
        """
        Extract trading signals from a strategy result.
        Default implementation returns result.signals.
        Override for custom signal logic.
        """
        return result.signals

    def get_config_schema(self) -> Dict[str, Any]:
        """
        Return JSON Schema for strategy configuration.
        Used by frontend to render dynamic config forms.
        """
        return {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        }

    def validate_data(self, prices_df: pd.DataFrame) -> bool:
        """Check if input data meets minimum requirements."""
        if prices_df is None or prices_df.empty:
            return False
        if len(prices_df) < self.min_data_points:
            return False
        # Check for required columns (case-insensitive)
        cols_lower = {c.lower() for c in prices_df.columns}
        required_cols = {"open", "high", "low", "close", "volume"}
        if not required_cols.issubset(cols_lower):
            return False
        return True

    def __repr__(self):
        return f"<Strategy: {self.name} v{self.version} ({self.layer.value})>"
