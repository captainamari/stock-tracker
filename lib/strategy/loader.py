"""
Strategy Loader
================
Registers all available strategies (adapters + new plugins) with the global registry.

Call load_all_strategies() at application startup (e.g., in web/app.py or pipeline scripts)
to populate the registry before using it.

Usage:
    from lib.strategy.loader import load_all_strategies
    load_all_strategies()

    # Now use the registry
    from lib.strategy import registry
    result = registry.run("momentum_v3", "NVDA", prices_df)
"""

import logging
from lib.strategy import registry

logger = logging.getLogger(__name__)


_loaded = False


def load_all_strategies():
    """
    Register all strategy plugins with the global registry.
    Idempotent — safe to call multiple times.

    This includes:
    - Legacy strategy adapters (market_pulse, stage2, vcp, bottom_fisher, buying_checklist)
    - Momentum V3 family (market_sentiment, sector_momentum, momentum_v3)
    """
    global _loaded
    if _loaded:
        return registry
    _loaded = True

    # Legacy adapters
    from lib.strategy.adapters import (
        MarketPulseAdapter,
        Stage2Adapter,
        VCPAdapter,
        BottomFisherAdapter,
        BuyingChecklistAdapter,
    )
    registry.register(MarketPulseAdapter)
    registry.register(Stage2Adapter)
    registry.register(VCPAdapter)
    registry.register(BottomFisherAdapter)
    registry.register(BuyingChecklistAdapter)

    # Momentum V3 family
    from lib.strategy.momentum_v3.strategy import (
        MomentumV3Strategy,
        SectorMomentumStrategy,
        MarketSentimentStrategy,
    )
    registry.register(MomentumV3Strategy)
    registry.register(SectorMomentumStrategy)
    registry.register(MarketSentimentStrategy)

    logger.info(f"Strategy registry loaded: {len(registry.list_names())} strategies")
    return registry
