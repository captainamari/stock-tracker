"""
Strategy Registry
==================
Central registry for strategy discovery, registration, and execution.

Supports:
- Decorator-based registration
- Auto-discovery from packages
- Batch execution across all/selected strategies
- Strategy metadata queries for frontend
"""

import importlib
import logging
import pkgutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Type

import pandas as pd

from lib.strategy.base import (
    BaseStrategy,
    StrategyLayer,
    StrategyResult,
    Signal,
    SignalType,
    Urgency,
)

logger = logging.getLogger(__name__)


class StrategyRegistry:
    """
    Registry that manages all available strategies.

    Usage:
        registry = StrategyRegistry()

        # Manual registration
        registry.register(MyStrategy)

        # Auto-discover from package
        registry.discover("lib.strategy")

        # Run strategies
        result = registry.run("momentum_v3", "NVDA", prices_df)
        results = registry.run_all("NVDA", prices_df)
    """

    def __init__(self):
        self._strategies: Dict[str, BaseStrategy] = {}
        self._classes: Dict[str, Type[BaseStrategy]] = {}

    def register(self, strategy_cls: Type[BaseStrategy]) -> Type[BaseStrategy]:
        """
        Register a strategy class. Can be used as decorator.

        @registry.register
        class MyStrategy(BaseStrategy):
            ...
        """
        if not isinstance(strategy_cls, type) or not issubclass(strategy_cls, BaseStrategy):
            raise TypeError(f"{strategy_cls} must be a subclass of BaseStrategy")

        instance = strategy_cls()
        name = instance.name

        if not name:
            raise ValueError(f"{strategy_cls.__name__} must define a 'name' attribute")

        if name in self._strategies:
            logger.warning(
                f"Strategy '{name}' already registered, overwriting with {strategy_cls.__name__}"
            )

        self._strategies[name] = instance
        self._classes[name] = strategy_cls
        logger.info(f"Registered strategy: {name} v{instance.version} ({instance.layer.value})")

        return strategy_cls

    def unregister(self, name: str) -> bool:
        """Remove a strategy from the registry."""
        if name in self._strategies:
            del self._strategies[name]
            del self._classes[name]
            return True
        return False

    def get(self, name: str) -> Optional[BaseStrategy]:
        """Get a strategy instance by name."""
        return self._strategies.get(name)

    def get_all(self) -> Dict[str, BaseStrategy]:
        """Get all registered strategies."""
        return dict(self._strategies)

    def get_by_layer(self, layer: StrategyLayer) -> Dict[str, BaseStrategy]:
        """Get strategies filtered by layer."""
        return {
            name: s for name, s in self._strategies.items()
            if s.layer == layer
        }

    def list_names(self) -> List[str]:
        """Get list of all registered strategy names."""
        return list(self._strategies.keys())

    def list_metadata(self) -> List[Dict[str, Any]]:
        """Get metadata for all strategies (for frontend display)."""
        return [
            {
                "name": s.name,
                "display_name": s.display_name,
                "version": s.version,
                "layer": s.layer.value,
                "description": s.description,
                "requires_market_data": s.requires_market_data,
                "requires_sector_data": s.requires_sector_data,
                "min_data_points": s.min_data_points,
                "config_schema": s.get_config_schema(),
            }
            for s in self._strategies.values()
        ]

    def run(
        self,
        name: str,
        symbol: str,
        prices_df: pd.DataFrame,
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[StrategyResult]:
        """
        Run a single strategy on a symbol.

        Returns StrategyResult or None if strategy not found / data invalid.
        """
        strategy = self._strategies.get(name)
        if not strategy:
            logger.error(f"Strategy '{name}' not found in registry")
            return None

        if not strategy.validate_data(prices_df):
            logger.warning(
                f"Insufficient data for {name} on {symbol} "
                f"(got {len(prices_df)} rows, need {strategy.min_data_points})"
            )
            return None

        try:
            start = time.time()
            result = strategy.compute(symbol, prices_df, context)
            elapsed = time.time() - start
            logger.debug(f"{name}.compute({symbol}) took {elapsed:.3f}s")
            return result
        except Exception as e:
            logger.error(f"Error running {name} on {symbol}: {e}", exc_info=True)
            return None

    def run_all(
        self,
        symbol: str,
        prices_df: pd.DataFrame,
        context: Optional[Dict[str, Any]] = None,
        strategies: Optional[List[str]] = None,
        layer: Optional[StrategyLayer] = None,
    ) -> Dict[str, StrategyResult]:
        """
        Run multiple strategies on a symbol.

        Args:
            symbol: Ticker symbol
            prices_df: Price data
            context: Shared context (market data, sector data, config)
            strategies: Optional list of strategy names to run (default: all)
            layer: Optional filter by layer

        Returns:
            Dict mapping strategy_name -> StrategyResult
        """
        results = {}

        target_strategies = self._strategies
        if strategies:
            target_strategies = {
                n: s for n, s in self._strategies.items() if n in strategies
            }
        if layer:
            target_strategies = {
                n: s for n, s in target_strategies.items() if s.layer == layer
            }

        for name, strategy in target_strategies.items():
            result = self.run(name, symbol, prices_df, context)
            if result:
                results[name] = result

        return results

    def run_batch(
        self,
        symbols: List[str],
        prices_map: Dict[str, pd.DataFrame],
        context: Optional[Dict[str, Any]] = None,
        strategies: Optional[List[str]] = None,
    ) -> Dict[str, Dict[str, StrategyResult]]:
        """
        Run strategies on multiple symbols.

        Returns:
            Dict mapping symbol -> {strategy_name -> StrategyResult}
        """
        all_results = {}
        for symbol in symbols:
            prices_df = prices_map.get(symbol)
            if prices_df is None or prices_df.empty:
                continue
            all_results[symbol] = self.run_all(symbol, prices_df, context, strategies)
        return all_results

    def discover(self, package_path: str = "lib.strategy") -> int:
        """
        Auto-discover and register strategies from a Python package.

        Scans for submodules and imports them. Strategies that use
        @registry.register decorator will be auto-registered on import.

        Args:
            package_path: Dotted path to the package (e.g., "lib.strategy")

        Returns:
            Number of newly registered strategies.
        """
        count_before = len(self._strategies)

        try:
            package = importlib.import_module(package_path)
        except ImportError as e:
            logger.error(f"Cannot import package '{package_path}': {e}")
            return 0

        package_dir = Path(package.__file__).parent

        for finder, module_name, is_pkg in pkgutil.walk_packages(
            [str(package_dir)], prefix=f"{package_path}."
        ):
            # Skip __init__ and base/registry modules
            if module_name.endswith(("__init__", ".base", ".registry")):
                continue
            try:
                importlib.import_module(module_name)
                logger.debug(f"Imported strategy module: {module_name}")
            except Exception as e:
                logger.warning(f"Failed to import {module_name}: {e}")

        new_count = len(self._strategies) - count_before
        logger.info(
            f"Discovery complete: found {new_count} new strategies "
            f"(total: {len(self._strategies)})"
        )
        return new_count
