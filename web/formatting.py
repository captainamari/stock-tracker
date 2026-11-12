"""Names and units for saved measurements; no strategy or price computation."""
import re

METRICS = {
    'price': ('Adjusted close (USD)', '复权收盘价（美元）'),
    'current_close': ('Adjusted close (USD)', '复权收盘价（美元）'),
    'current_price': ('Adjusted close (USD)', '复权收盘价（美元）'),
    'rsi': ('RSI (0–100)', '相对强弱 RSI（0–100）'),
    'atr': ('Average true range (USD)', '平均真实波幅（美元）'),
    'trend_power': ('Trend score (points)', '趋势评分（分）'),
    'vcp_score': ('Contraction score (points)', '收缩评分（分）'),
    'bf_score': ('Countertrend score (points)', '逆势评分（分）'),
    'bc_score': ('Checklist score (points)', '条件清单评分（分）'),
    'passed': ('Conditions met (count)', '已满足条件（项）'),
    'total': ('Conditions assessed (count)', '检查条件（项）'),
    'vol_ratio': ('Volume ratio (×)', '成交量比（倍）'),
    'volume_ratio': ('Volume ratio (×)', '成交量比（倍）'),
    'week52_high': ('52-week high (USD)', '52周高点（美元）'),
    'week52_low': ('52-week low (USD)', '52周低点（美元）'),
    'pct_from_high': ('From 52-week high (%)', '距52周高点（%）'),
    'pct_from_low': ('From 52-week low (%)', '距52周低点（%）'),
    'pct_from_52w_high': ('From 52-week high (%)', '距52周高点（%）'),
    'pct_from_52w_low': ('From 52-week low (%)', '距52周低点（%）'),
    'pct_from_20d_high': ('From 20-session high (%)', '距20日高点（%）'),
    'pct_from_sma200': ('From SMA200 (%)', '距200日均线（%）'),
    'pct_from_sma10': ('From SMA10 (%)', '距10日均线（%）'),
    'pct_above_sma200': ('Above SMA200 (%)', '高于200日均线（%）'),
    'pct_above_sma50': ('Above SMA50 (%)', '高于50日均线（%）'),
    'stock_return_6m': ('126-session stock return (%)', '股票126交易日回报（%）'),
    'spy_return_6m': ('Aligned SPY return (%)', '同期 SPY 回报（%）'),
    'chg_5d': ('5-session return (%)', '5交易日涨跌幅（%）'),
    'chg_20d': ('20-session return (%)', '20交易日涨跌幅（%）'),
    'days_in_stage2': ('Stage 2 duration (calendar days)', 'Stage 2 持续（自然日）'),
    'impulse_streak': ('Weekly impulse streak (weeks)', '周线冲量连续（周）'),
    'vol_dry_days': ('Dry-volume sessions (count)', '缩量交易日（天）'),
    'vol_10d': ('10-session mean volume (shares)', '10日平均成交量（股）'),
    'vol_50d': ('50-session mean volume (shares)', '50日平均成交量（股）'),
    'bbw': ('Bollinger bandwidth (%)', '布林带宽（%）'),
    'bbw_percentile': ('Bandwidth percentile (0–100)', '布林带宽分位（0–100）'),
    'sma50_slope': ('SMA50 slope (%)', '50日均线斜率（%）'),
    'macd': ('MACD (USD)', 'MACD（美元）'),
    'macd_signal': ('MACD signal (USD)', 'MACD 信号线（美元）'),
    'macd_histogram': ('MACD histogram (USD)', 'MACD 柱值（美元）'),
    'macd_hist_prev': ('Previous MACD histogram (USD)', '前期 MACD 柱值（美元）'),
    'weekly_ema13': ('13-week EMA (USD)', '13周指数均线（美元）'),
    'weekly_macd_hist': ('Weekly MACD histogram (USD)', '周线 MACD 柱值（美元）'),
    'hv30': ('30-session annualized volatility (%)', '30日年化波动率（%）'),
    'vwap20': ('20-session volume-weighted price (USD)', '20日成交量加权均价（美元）'),
}


def metric_label(key, t):
    if key in METRICS:
        return t(*METRICS[key])
    ma = re.fullmatch(r'(sma|ema)_?(\d+)', key.lower())
    if ma:
        return t(f'{ma[2]}-session {ma[1].upper()} (USD)',
                 f'{ma[2]}日{"简单" if ma[1] == "sma" else "指数"}均线（美元）')
    support = re.fullmatch(r'support_sma(\d+)', key)
    if support:
        return t(f'SMA{support[1]} support (USD)', f'{support[1]}日均线支撑（美元）')
    return key.replace('_', ' ') + (' (%)' if 'pct' in key else '')
