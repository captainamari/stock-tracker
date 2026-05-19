"""
Momentum V3 Pipeline Runner
==============================
Runs the Momentum V3 strategy across all layers (Market → Sector → Stock)
and persists results to the database.

Usage:
    python -m lib.strategy.momentum_v3.runner          # Full run
    python -m lib.strategy.momentum_v3.runner --layer stock  # Stock only
    python -m lib.strategy.momentum_v3.runner --symbol NVDA  # Single stock
"""

import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

# Ensure project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from lib.db import (
    get_prices_as_dataframe,
    get_watchlist,
    get_sector_definitions,
    get_sector_mappings,
    save_momentum_score,
    save_momentum_scores_batch,
    save_score_history_batch,
    save_strategy_result,
    record_pipeline_run,
    record_signal_change,
    upsert_strategy_state,
    get_strategy_state,
)
from lib.strategy.momentum_v3.core import compute_composite_momentum_v2, get_regime
from lib.strategy.momentum_v3.signals import V3SignalEngine
from lib.strategy.momentum_v3.strategy import MomentumV3Strategy, SectorMomentumStrategy, MarketSentimentStrategy

logger = logging.getLogger(__name__)


# Market sentiment tickers
MARKET_TICKERS = ["SPY", "QQQ"]


def run_momentum_pipeline(
    symbols: Optional[List[str]] = None,
    layers: Optional[List[str]] = None,
    db_path=None,
) -> Dict[str, Any]:
    """
    Execute the full Momentum V3 pipeline.

    Phases:
        1. Market Sentiment (SPY, QQQ) → establishes market context
        2. Sector ETFs → establishes sector context
        3. Individual Stocks → uses market + sector context for relative strength

    Args:
        symbols: Specific stock symbols to run (default: all watchlist)
        layers: Layers to run: ['market', 'sector', 'stock'] (default: all)
        db_path: Optional database path override

    Returns:
        Summary dict with counts and timing.
    """
    start_time = time.time()
    layers = layers or ["market", "sector", "stock"]
    today = datetime.now().strftime("%Y-%m-%d")

    results_summary = {
        "date": today,
        "market": {"processed": 0, "signals": 0},
        "sector": {"processed": 0, "signals": 0},
        "stock": {"processed": 0, "signals": 0},
        "errors": [],
    }

    market_scores: Dict[str, float] = {}
    sector_scores: Dict[str, float] = {}

    # ── Phase 1: Market Sentiment ──
    if "market" in layers:
        logger.info("── Phase 1: Market Sentiment ──")
        strategy = MarketSentimentStrategy()

        for ticker in MARKET_TICKERS:
            try:
                prices_df = get_prices_as_dataframe(ticker, min_rows=30, db_path=db_path)
                if prices_df is None or prices_df.empty:
                    logger.warning(f"No price data for {ticker}")
                    continue

                result = strategy.compute(ticker, prices_df)
                if result and result.score is not None:
                    market_scores[ticker] = result.score
                    _persist_momentum_result(ticker, result, "market", today, db_path)
                    results_summary["market"]["processed"] += 1
                    if result.is_signal:
                        results_summary["market"]["signals"] += 1

            except Exception as e:
                logger.error(f"Error computing market sentiment for {ticker}: {e}")
                results_summary["errors"].append(f"market:{ticker}:{e}")

    # ── Phase 2: Sector ETFs ──
    if "sector" in layers:
        logger.info("── Phase 2: Sector ETFs ──")
        strategy = SectorMomentumStrategy()

        try:
            sectors = get_sector_definitions(enabled_only=True, db_path=db_path)
        except Exception:
            # Table might not exist yet, use defaults
            sectors = [
                {"sector_key": "semiconductors", "etf_symbol": "SMH", "sector_name": "Semiconductors/Storage"},
                {"sector_key": "defense", "etf_symbol": "ITA", "sector_name": "Defense/Drones"},
                {"sector_key": "software", "etf_symbol": "IGV", "sector_name": "Software/SaaS"},
                {"sector_key": "biotech", "etf_symbol": "XBI", "sector_name": "AI Healthcare/Biotech"},
            ]

        for sector in sectors:
            etf = sector.get("etf_symbol", "")
            if not etf or etf == "BASKET":
                # TODO: Implement basket computation
                continue

            try:
                prices_df = get_prices_as_dataframe(etf, min_rows=30, db_path=db_path)
                if prices_df is None or prices_df.empty:
                    logger.warning(f"No price data for sector ETF {etf}")
                    continue

                result = strategy.compute(etf, prices_df)
                if result and result.score is not None:
                    sector_scores[sector["sector_key"]] = result.score
                    _persist_momentum_result(etf, result, "sector", today, db_path)
                    results_summary["sector"]["processed"] += 1
                    if result.is_signal:
                        results_summary["sector"]["signals"] += 1

            except Exception as e:
                logger.error(f"Error computing sector momentum for {etf}: {e}")
                results_summary["errors"].append(f"sector:{etf}:{e}")

    # ── Phase 3: Individual Stocks ──
    if "stock" in layers:
        logger.info("── Phase 3: Individual Stocks ──")
        strategy = MomentumV3Strategy()

        # Get stock list
        if symbols:
            stock_symbols = symbols
        else:
            watchlist = get_watchlist(enabled_only=True, source_type="monitored", db_path=db_path)
            stock_symbols = [item["symbol"] for item in watchlist]

        # Get sector mappings
        try:
            mappings = {m["stock_symbol"]: m for m in get_sector_mappings(db_path=db_path)}
        except Exception:
            mappings = {}

        context = {
            "market_scores": market_scores,
            "sector_scores": sector_scores,
        }

        for symbol in stock_symbols:
            try:
                prices_df = get_prices_as_dataframe(symbol, min_rows=30, db_path=db_path)
                if prices_df is None or prices_df.empty:
                    continue

                # Add stock-specific sector info to context
                mapping = mappings.get(symbol, {})
                if mapping:
                    strategy.stock_sectors[symbol] = mapping.get("sector_key")

                result = strategy.compute(symbol, prices_df, context)
                if result and result.score is not None:
                    _persist_momentum_result(symbol, result, "stock", today, db_path)
                    _check_signal_change(symbol, result, today, db_path)
                    results_summary["stock"]["processed"] += 1
                    if result.is_signal:
                        results_summary["stock"]["signals"] += 1

            except Exception as e:
                logger.error(f"Error computing momentum for {symbol}: {e}")
                results_summary["errors"].append(f"stock:{symbol}:{e}")

    # Record pipeline run
    elapsed = time.time() - start_time
    try:
        record_pipeline_run(today, "momentum_v3", "ok", duration=elapsed, db_path=db_path)
    except Exception as e:
        logger.warning(f"Failed to record pipeline run: {e}")

    results_summary["duration_seconds"] = round(elapsed, 2)
    logger.info(
        f"Momentum V3 pipeline complete: "
        f"Market={results_summary['market']['processed']}, "
        f"Sector={results_summary['sector']['processed']}, "
        f"Stock={results_summary['stock']['processed']}, "
        f"Duration={elapsed:.1f}s"
    )

    return results_summary


def _persist_momentum_result(
    symbol: str, result, layer: str, date_str: str, db_path=None
):
    """Save momentum result to both strategy_results and momentum_scores tables."""
    metrics = result.metrics or {}

    # Save to strategy_results (unified table)
    save_strategy_result(
        symbol=symbol,
        date_str=date_str,
        strategy=result.strategy,
        is_signal=result.is_signal,
        score=result.score,
        passed=result.passed,
        total=result.total,
        conditions=result.conditions,
        condition_details=result.condition_details,
        metrics=metrics,
        summary=result.summary,
        db_path=db_path,
    )

    # Save to momentum_scores (dedicated table)
    v3_details = result.condition_details or {}
    save_momentum_score(
        symbol=symbol,
        date_str=date_str,
        layer=layer,
        final_score=result.score,
        raw_score=metrics.get("raw_score"),
        regime=metrics.get("regime"),
        delta_1d=metrics.get("delta_1d"),
        delta_5d=metrics.get("score_5d_change"),
        consecutive_above_65=metrics.get("consecutive_above_65", 0),
        consecutive_above_70=metrics.get("consecutive_above_70", 0),
        consecutive_below_60=metrics.get("consecutive_below_60", 0),
        signals=v3_details.get("v3_signals", []),
        position_advice=metrics.get("position_advice"),
        urgency=v3_details.get("urgency", "NONE"),
        relative_strength=metrics.get("relative_strength", {}),
        price=metrics.get("price"),
        daily_change_pct=metrics.get("daily_change_pct"),
        db_path=db_path,
    )

    # Save to score_history
    if result.score is not None:
        save_score_history_batch([{
            "symbol": symbol,
            "date": date_str,
            "strategy": result.strategy,
            "score": result.score,
            "regime": metrics.get("regime"),
        }], db_path=db_path)


def _check_signal_change(symbol: str, result, date_str: str, db_path=None):
    """Check if signal state changed and record it."""
    strategy_name = result.strategy
    current_active = result.is_signal

    prev_state = get_strategy_state(symbol, strategy_name, db_path=db_path)
    was_active = prev_state.get("is_active", False) if prev_state else False

    if current_active and not was_active:
        # New entry signal
        record_signal_change(
            symbol=symbol,
            date_str=date_str,
            strategy=strategy_name,
            change_type="entry",
            price=result.metrics.get("price"),
            score=result.score,
            details={"signals": result.condition_details.get("v3_signals", [])},
            db_path=db_path,
        )
        upsert_strategy_state(
            symbol=symbol,
            strategy=strategy_name,
            is_active=True,
            entry_date=date_str,
            entry_price=result.metrics.get("price"),
            extra={"urgency": result.condition_details.get("urgency", "NONE")},
            db_path=db_path,
        )
    elif not current_active and was_active:
        # Signal lost / exit
        record_signal_change(
            symbol=symbol,
            date_str=date_str,
            strategy=strategy_name,
            change_type="exit",
            price=result.metrics.get("price"),
            score=result.score,
            details={"signals": result.condition_details.get("v3_signals", [])},
            db_path=db_path,
        )
        upsert_strategy_state(
            symbol=symbol,
            strategy=strategy_name,
            is_active=False,
            extra={"exit_date": date_str},
            db_path=db_path,
        )
    elif current_active:
        # Still active, update state
        upsert_strategy_state(
            symbol=symbol,
            strategy=strategy_name,
            is_active=True,
            extra={
                "urgency": result.condition_details.get("urgency", "NONE"),
                "score": result.score,
            },
            db_path=db_path,
        )


if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="Momentum V3 Pipeline Runner")
    parser.add_argument("--layer", choices=["market", "sector", "stock"],
                        help="Run specific layer only")
    parser.add_argument("--symbol", type=str, help="Run for a specific stock symbol")
    parser.add_argument("--symbols", type=str, help="Comma-separated symbols")
    args = parser.parse_args()

    layers = [args.layer] if args.layer else None
    symbols = None
    if args.symbol:
        symbols = [args.symbol.upper()]
    elif args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",")]

    print("=" * 70)
    print("  🚀 Momentum V3 Pipeline Runner")
    print(f"  📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    summary = run_momentum_pipeline(symbols=symbols, layers=layers)

    print(f"\n{'─' * 70}")
    print(f"  ✅ Complete in {summary['duration_seconds']}s")
    print(f"     Market: {summary['market']['processed']} processed, {summary['market']['signals']} signals")
    print(f"     Sector: {summary['sector']['processed']} processed, {summary['sector']['signals']} signals")
    print(f"     Stock:  {summary['stock']['processed']} processed, {summary['stock']['signals']} signals")
    if summary['errors']:
        print(f"     ⚠️ Errors: {len(summary['errors'])}")
        for err in summary['errors'][:5]:
            print(f"       - {err}")
    print(f"{'─' * 70}")
