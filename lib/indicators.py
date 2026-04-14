"""
Stock Tracker — 技术指标计算库
从现有策略脚本中提取的公共技术指标函数。
所有策略共享同一套计算逻辑，避免重复代码。

支持的指标：
  - SMA (Simple Moving Average)
  - EMA (Exponential Moving Average)
  - RSI (Relative Strength Index, Wilder 平滑)
  - MACD (Moving Average Convergence Divergence)
  - ATR (Average True Range)
  - Bollinger Bandwidth
  - 连涨连跌天数
  - RSI 底背离检测
  - MACD 底背离检测
  - 锤子线/十字星检测
"""

import pandas as pd
import numpy as np
from typing import Tuple, Optional


# ============================================================
# 基础移动平均
# ============================================================
def sma(close: pd.Series, window: int) -> pd.Series:
    """简单移动平均"""
    return close.rolling(window=window).mean()


def ema(close: pd.Series, span: int) -> pd.Series:
    """指数移动平均"""
    return close.ewm(span=span, adjust=False).mean()


# ============================================================
# RSI (Relative Strength Index)
# ============================================================
def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """
    RSI（Wilder 平滑）
    返回完整的 RSI Series (前 period-1 行为 NaN)
    """
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


# ============================================================
# MACD
# ============================================================
def macd(close: pd.Series, fast: int = 12, slow: int = 26,
         signal: int = 9) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    MACD 指标
    返回: (macd_line, signal_line, histogram)
    """
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


# ============================================================
# ATR (Average True Range)
# ============================================================
def atr(data: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Average True Range
    data 须含 'High', 'Low', 'Close' 列
    """
    high, low, close = data['High'], data['Low'], data['Close']
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


# ============================================================
# Bollinger Bandwidth
# ============================================================
def bollinger_bandwidth(close: pd.Series, period: int = 20,
                        std_mult: float = 2.0) -> pd.Series:
    """
    布林带宽度 (BBW) = (Upper - Lower) / Middle × 100
    用于 VCP 波动率收缩检测
    """
    sma_val = close.rolling(window=period).mean()
    std = close.rolling(window=period).std()
    upper = sma_val + std_mult * std
    lower = sma_val - std_mult * std
    return ((upper - lower) / sma_val) * 100


def bbw_percentile(close: pd.Series, period: int = 20, std_mult: float = 2.0,
                   lookback: int = 120) -> float:
    """
    计算当前 BBW 在历史中的分位数 (0-100)
    低分位 = 波动率收缩 = VCP 候选
    """
    bbw = bollinger_bandwidth(close, period, std_mult)
    current = bbw.iloc[-1]
    history = bbw.tail(lookback).dropna()
    if len(history) == 0:
        return 50.0
    return float((history < current).sum() / len(history) * 100)


# ============================================================
# 连涨/连跌天数
# ============================================================
def consecutive_streak(close: pd.Series) -> Tuple[str, int]:
    """
    计算连涨/连跌天数
    返回: (方向字符串如 "+3d"/"-2d"/"0d", 有符号天数)
    """
    if len(close) < 2:
        return "0d", 0

    diffs = close.diff().dropna()

    # 连涨
    up_count = 0
    for val in reversed(diffs.values):
        if val > 0:
            up_count += 1
        else:
            break

    # 连跌
    down_count = 0
    for val in reversed(diffs.values):
        if val < 0:
            down_count += 1
        else:
            break

    if up_count > 0:
        return f"+{up_count}d", up_count
    elif down_count > 0:
        return f"-{down_count}d", -down_count
    else:
        return "0d", 0


# ============================================================
# 背离检测
# ============================================================
def detect_rsi_divergence(close: pd.Series, rsi_series: pd.Series,
                          window: int = 20) -> Tuple[bool, str]:
    """
    检测 RSI 底背离：价格创近期新低但 RSI 未创新低
    返回: (is_divergence, detail_string)
    """
    if len(close) < window + 5 or len(rsi_series.dropna()) < window + 5:
        return False, ""

    recent_close = close.tail(window)
    half = window // 2

    first_half = recent_close.iloc[:half]
    second_half = recent_close.iloc[half:]

    if len(first_half) < 3 or len(second_half) < 3:
        return False, ""

    first_low_idx = first_half.idxmin()
    second_low_idx = second_half.idxmin()

    first_price = first_half[first_low_idx]
    second_price = second_half[second_low_idx]

    first_rsi = rsi_series.loc[first_low_idx] if first_low_idx in rsi_series.index else None
    second_rsi = rsi_series.loc[second_low_idx] if second_low_idx in rsi_series.index else None

    if first_rsi is None or second_rsi is None:
        return False, ""
    if pd.isna(first_rsi) or pd.isna(second_rsi):
        return False, ""

    # 底背离条件：第二次价格更低（或持平），但 RSI 更高
    if second_price <= first_price * 1.01 and second_rsi > first_rsi + 2:
        return True, f"价格低点 ${second_price:.2f} ≤ ${first_price:.2f}，RSI 抬升 {first_rsi:.1f}→{second_rsi:.1f}"

    return False, ""


def detect_macd_divergence(close: pd.Series, histogram: pd.Series,
                           window: int = 20) -> Tuple[bool, str]:
    """
    检测 MACD 底背离：价格创新低但 MACD 柱状图抬高
    返回: (is_divergence, detail_string)
    """
    if len(close) < window + 5 or len(histogram.dropna()) < window + 5:
        return False, ""

    recent_close = close.tail(window)
    recent_hist = histogram.tail(window)
    half = window // 2

    first_half = recent_close.iloc[:half]
    second_half = recent_close.iloc[half:]

    if len(first_half) < 3 or len(second_half) < 3:
        return False, ""

    first_low_idx = first_half.idxmin()
    second_low_idx = second_half.idxmin()

    first_price = first_half[first_low_idx]
    second_price = second_half[second_low_idx]

    first_hist = histogram.loc[first_low_idx] if first_low_idx in histogram.index else None
    second_hist = histogram.loc[second_low_idx] if second_low_idx in histogram.index else None

    if first_hist is None or second_hist is None:
        return False, ""
    if pd.isna(first_hist) or pd.isna(second_hist):
        return False, ""

    # 底背离：价格更低但 MACD 柱状图更高（不那么负）
    if second_price <= first_price * 1.01 and second_hist > first_hist + 0.01:
        return True, f"MACD 柱状图抬升 {first_hist:.3f}→{second_hist:.3f}"

    # 柱状图由负转正也是强信号
    if len(recent_hist) >= 3:
        if recent_hist.iloc[-2] < 0 and recent_hist.iloc[-1] > 0:
            return True, "MACD 柱状图由负转正"

    return False, ""


# ============================================================
# K线形态检测
# ============================================================
def detect_hammer(data: pd.DataFrame,
                  body_ratio_max: float = 0.3,
                  lower_shadow_min: float = 2.0) -> Tuple[bool, str, str]:
    """
    检测锤子线/十字星形态（最后一根 K 线）
    返回: (is_pattern, pattern_name, detail)
    """
    if len(data) < 2:
        return False, "", ""

    latest = data.iloc[-1]
    o, h, l, c = latest['Open'], latest['High'], latest['Low'], latest['Close']

    full_range = h - l
    if full_range <= 0:
        return False, "", ""

    body = abs(c - o)
    body_ratio = body / full_range
    upper_shadow = h - max(o, c)
    lower_shadow = min(o, c) - l

    # 十字星：实体极小
    if body_ratio < 0.1:
        return True, "十字星", f"实体占比 {body_ratio:.1%}，高度犹豫信号"

    # 锤子线：小实体 + 长下影线
    if (body_ratio < body_ratio_max and
            body > 0 and
            lower_shadow >= body * lower_shadow_min and
            upper_shadow < body):
        return True, "锤子线", f"下影线 {lower_shadow / body:.1f}x 实体，空方力竭信号"

    return False, "", ""


# ============================================================
# 涨跌幅计算
# ============================================================
def pct_change(close: pd.Series, periods: int) -> Optional[float]:
    """计算 N 日涨跌幅 (%)，数据不足返回 None"""
    if len(close) < periods + 1:
        return None
    return round((close.iloc[-1] / close.iloc[-(periods + 1)] - 1) * 100, 1)


def pct_from_value(current: float, reference: float) -> float:
    """计算相对于参考值的百分比偏差"""
    if reference == 0:
        return 0.0
    return round((current / reference - 1) * 100, 1)


# ============================================================
# DataFrame 工具
# ============================================================
def normalize_tz(df: pd.DataFrame) -> pd.DataFrame:
    """统一 DataFrame 时间索引为 tz-naive UTC，避免混合时区问题"""
    if df is None or not isinstance(df.index, pd.DatetimeIndex):
        return df
    if df.index.tz is not None:
        df.index = df.index.tz_convert('UTC').tz_localize(None)
    else:
        try:
            df.index = pd.to_datetime(df.index, utc=True).tz_localize(None)
        except Exception:
            pass
    return df
