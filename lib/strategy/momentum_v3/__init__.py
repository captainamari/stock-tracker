"""
Momentum V3 Strategy Plugin
=============================
Three-layer architecture:
    Layer 0: Market Sentiment (SPY, QQQ) — Risk-on/Risk-off gauge
    Layer 1: Sector ETF — Hardware/supply-chain sector momentum
    Layer 2: Individual Stock — Independent stock momentum

This module implements the full Momentum V3 strategy as a BaseStrategy plugin,
integrating with the strategy registry for unified pipeline execution.
"""

from lib.strategy.momentum_v3.strategy import MomentumV3Strategy
from lib.strategy.momentum_v3.core import (
    compute_composite_momentum_v2,
    compute_full_momentum,
    get_regime,
    MomentumScores,
)
from lib.strategy.momentum_v3.signals import V3SignalEngine, V3Signal

__all__ = [
    "MomentumV3Strategy",
    "compute_composite_momentum_v2",
    "compute_full_momentum",
    "get_regime",
    "MomentumScores",
    "V3SignalEngine",
    "V3Signal",
]
