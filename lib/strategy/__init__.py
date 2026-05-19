"""
Strategy Plugin Architecture
=============================
Provides a registry-based plugin system for trading strategies.

Usage:
    from lib.strategy import registry, BaseStrategy, StrategyResult, Signal

    # Register a new strategy
    @registry.register
    class MyStrategy(BaseStrategy):
        name = "my_strategy"
        ...

    # Run all strategies for a symbol
    results = registry.run_all(symbol, prices_df)

    # Run a specific strategy
    result = registry.run("momentum_v3", symbol, prices_df)
"""

from lib.strategy.base import (
    BaseStrategy,
    StrategyResult,
    Signal,
    SignalType,
    Urgency,
    StrategyLayer,
)
from lib.strategy.registry import StrategyRegistry

# Global registry instance
registry = StrategyRegistry()

__all__ = [
    "BaseStrategy",
    "StrategyResult",
    "Signal",
    "SignalType",
    "Urgency",
    "StrategyLayer",
    "StrategyRegistry",
    "registry",
]
