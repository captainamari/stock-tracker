"""
Momentum V3 Strategy — Core Computation Engine
================================================
Composite Momentum Score V2 algorithm + V3 Signal Engine.

Ported from momentum_yfinance.py with clean interface for the strategy registry.

Algorithm:
    Raw Score = ROC(10)×0.15 + ROC(20)×0.20 + RSI(14)×0.15
              + MA_Slope(20,5)×0.20 + Price_vs_MA20×0.15 + NewHighRate(20)×0.15
    Final Score = Raw + min(5, consecutive_strong_days × 0.5)

V3 Improvements (3-year backtest validated):
    1. Entry confirmation: Level 1 (Score≥70 → 50%) + Level 2 (≥65 for 3 days → 100%)
    2. Graduated exit: Yellow (2 days drop>3/day) → Red (break 60) → Full sell (break 50)
    3. Score change rate monitoring: Single day drop>5 = 88% probability of continuation
    4. False breakout filter: 5-day climb <+10 = possible fake breakout
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


@dataclass
class MomentumScores:
    """Container for momentum computation results."""
    dates: List[str]
    closes: List[float]
    raw_scores: List[Optional[float]]
    final_scores: List[Optional[float]]
    roc_10: List[Optional[float]]
    roc_20: List[Optional[float]]
    rsi_14: List[Optional[float]]
    ma_slope: List[Optional[float]]
    price_vs_ma20: List[Optional[float]]
    new_high_rate: List[Optional[float]]


def calc_roc(closes: List[float], period: int) -> List[Optional[float]]:
    """Rate of Change."""
    return [
        None if i < period else (closes[i] - closes[i - period]) / closes[i - period] * 100
        for i in range(len(closes))
    ]


def calc_rsi(closes: List[float], period: int = 14) -> List[Optional[float]]:
    """Wilder RSI."""
    n = len(closes)
    if n < period + 1:
        return [None] * n

    rsi = [None] * period
    gains, losses = [], []

    for i in range(1, n):
        change = closes[i] - closes[i - 1]
        gains.append(max(0, change))
        losses.append(max(0, -change))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    if avg_loss == 0:
        rsi.append(100.0)
    else:
        rsi.append(100 - (100 / (1 + avg_gain / avg_loss)))

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            rsi.append(100.0)
        else:
            rsi.append(100 - (100 / (1 + avg_gain / avg_loss)))

    return rsi


def calc_sma(closes: List[float], period: int) -> List[Optional[float]]:
    """Simple Moving Average."""
    return [
        None if i < period - 1 else sum(closes[i - period + 1: i + 1]) / period
        for i in range(len(closes))
    ]


def calc_ma_slope(
    closes: List[float], ma_period: int = 20, slope_period: int = 5
) -> List[Optional[float]]:
    """Annualized MA slope as percentage."""
    ma = calc_sma(closes, ma_period)
    slope = []
    for i in range(len(ma)):
        if ma[i] is None or i < slope_period or ma[i - slope_period] is None:
            slope.append(None)
        else:
            slope.append(
                (ma[i] - ma[i - slope_period]) / ma[i - slope_period] * (252 / slope_period) * 100
            )
    return slope


def calc_new_high_rate(closes: List[float], period: int = 20) -> List[Optional[float]]:
    """Percentage of days that set a new rolling high within period."""
    rates = []
    for i in range(len(closes)):
        if i < period:
            rates.append(None)
        else:
            window = closes[i - period + 1: i + 1]
            count = 0
            running_max = window[0]
            for j in range(1, len(window)):
                if window[j] > running_max:
                    count += 1
                    running_max = window[j]
            rates.append(count / (period - 1) * 100)
    return rates


def compute_composite_momentum_v2(closes: List[float]) -> Tuple[List[Optional[float]], List[Optional[float]]]:
    """
    Composite Momentum Score V2.

    Returns:
        (final_scores, raw_scores) — both are lists aligned with closes.
    """
    n = len(closes)
    if n < 25:
        return [None] * n, [None] * n

    roc_10 = calc_roc(closes, 10)
    roc_20 = calc_roc(closes, 20)
    rsi_14 = calc_rsi(closes, 14)
    ma_slope = calc_ma_slope(closes, 20, 5)
    ma20 = calc_sma(closes, 20)
    new_high_rate = calc_new_high_rate(closes, 20)

    price_vs_ma = [
        None if ma20[i] is None else (closes[i] - ma20[i]) / ma20[i] * 100
        for i in range(n)
    ]

    raw_scores: List[Optional[float]] = []
    for i in range(n):
        if any(v is None for v in [roc_20[i], rsi_14[i], ma_slope[i], price_vs_ma[i]]):
            raw_scores.append(None)
            continue

        roc10_score = min(100, max(0, (roc_10[i] + 15) / 45 * 100)) if roc_10[i] is not None else 50
        roc20_score = min(100, max(0, (roc_20[i] + 20) / 55 * 100))
        rsi_score = rsi_14[i]
        slope_score = min(100, max(0, (ma_slope[i] + 100) / 400 * 100))
        pma_score = min(100, max(0, (price_vs_ma[i] + 8) / 23 * 100))
        nhr_score = new_high_rate[i] if new_high_rate[i] is not None else 50

        score = (
            roc10_score * 0.15
            + roc20_score * 0.20
            + rsi_score * 0.15
            + slope_score * 0.20
            + pma_score * 0.15
            + nhr_score * 0.15
        )
        raw_scores.append(score)

    # Apply consecutive strong days bonus
    final_scores: List[Optional[float]] = []
    consecutive_strong = 0
    for i in range(n):
        if raw_scores[i] is None:
            final_scores.append(None)
            consecutive_strong = 0
            continue
        if raw_scores[i] >= 65:
            consecutive_strong += 1
        else:
            consecutive_strong = 0
        final_scores.append(min(100, raw_scores[i] + min(5.0, consecutive_strong * 0.5)))

    return final_scores, raw_scores


def compute_full_momentum(closes: List[float], dates: List[str]) -> Optional[MomentumScores]:
    """
    Compute all momentum indicators for a price series.

    Args:
        closes: List of closing prices (chronological order)
        dates: List of date strings aligned with closes

    Returns:
        MomentumScores dataclass or None if insufficient data.
    """
    if len(closes) < 25:
        return None

    final_scores, raw_scores = compute_composite_momentum_v2(closes)
    roc_10 = calc_roc(closes, 10)
    roc_20 = calc_roc(closes, 20)
    rsi_14 = calc_rsi(closes, 14)
    ma_slope = calc_ma_slope(closes, 20, 5)
    ma20 = calc_sma(closes, 20)
    price_vs_ma = [
        None if ma20[i] is None else (closes[i] - ma20[i]) / ma20[i] * 100
        for i in range(len(closes))
    ]
    new_high_rate = calc_new_high_rate(closes, 20)

    return MomentumScores(
        dates=dates,
        closes=closes,
        raw_scores=raw_scores,
        final_scores=final_scores,
        roc_10=roc_10,
        roc_20=roc_20,
        rsi_14=rsi_14,
        ma_slope=ma_slope,
        price_vs_ma20=price_vs_ma,
        new_high_rate=new_high_rate,
    )


def get_regime(score: Optional[float]) -> Tuple[str, str]:
    """
    Map score to regime label and emoji.

    Returns:
        (regime_name, emoji)
    """
    if score is None:
        return "N/A", "⬜"
    elif score >= 70:
        return "STRONG_TREND", "🟢"
    elif score >= 60:
        return "STRONG", "🟡"
    elif score >= 40:
        return "NEUTRAL", "⚪"
    else:
        return "WEAK", "🔴"
