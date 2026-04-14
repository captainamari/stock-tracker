"""
Stock Tracker — 数据模型定义
使用 dataclass 定义各策略的输入/输出数据结构，
作为脚本层与数据库层之间的桥梁。

设计原则：
  - 纯 Python dataclass，零外部依赖
  - 提供 to_db_dict() 方法，方便写入 strategy_results 表
  - 提供 from_db_row() 类方法，方便从数据库行还原
"""

from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, List, Any
from datetime import datetime
import json


# ============================================================
# Ticker 配置
# ============================================================
@dataclass
class TickerInfo:
    """观察列表中的单只股票"""
    symbol: str
    name: str
    sector: str = ""
    enabled: bool = True
    source_type: str = "monitored"  # 'monitored' | 'yfinance_only'
    yf_ticker: Optional[str] = None

    def to_db_dict(self) -> Dict:
        return {
            'symbol': self.symbol,
            'name': self.name,
            'sector': self.sector,
            'enabled': self.enabled,
            'source_type': self.source_type,
            'yf_ticker': self.yf_ticker,
        }

    @classmethod
    def from_json(cls, data: Dict) -> 'TickerInfo':
        """从 tickers.json 格式构建"""
        return cls(
            symbol=data['symbol'],
            name=data.get('name', data['symbol']),
            sector=data.get('sector', ''),
            enabled=data.get('enabled', True),
            source_type=data.get('source_type', 'monitored'),
            yf_ticker=data.get('yf_ticker'),
        )


# ============================================================
# 价格数据
# ============================================================
@dataclass
class PriceRow:
    """单条日线价格"""
    symbol: str
    date: str  # YYYY-MM-DD
    open: float
    high: float
    low: float
    close: float
    volume: int = 0

    def to_db_dict(self) -> Dict:
        return {
            'date': self.date,
            'open': self.open,
            'high': self.high,
            'low': self.low,
            'close': self.close,
            'volume': self.volume,
        }

    @classmethod
    def from_csv_row(cls, symbol: str, row: Dict) -> 'PriceRow':
        """从 CSV DictReader 行构建"""
        return cls(
            symbol=symbol,
            date=row['Date'],
            open=float(row['Open']),
            high=float(row['High']),
            low=float(row['Low']),
            close=float(row['Close']),
            volume=int(float(row.get('Volume', 0) or 0)),
        )


# ============================================================
# 策略结果基类
# ============================================================
@dataclass
class StrategyResult:
    """所有策略结果的基类"""
    symbol: str
    name: str
    sector: str
    price: float
    date: str  # YYYY-MM-DD
    strategy: str  # 'stage2' | 'vcp' | 'bottom_fisher'
    is_signal: bool = False
    score: float = 0
    passed: int = 0
    total: int = 0
    conditions: Dict[str, Optional[bool]] = field(default_factory=dict)
    condition_details: Dict[str, str] = field(default_factory=dict)
    metrics: Dict[str, Any] = field(default_factory=dict)

    def to_db_dict(self) -> Dict:
        """转换为 save_strategy_result() 所需的参数"""
        return {
            'symbol': self.symbol,
            'is_signal': self.is_signal,
            'score': self.score,
            'passed': self.passed,
            'total': self.total,
            'conditions': self.conditions,
            'condition_details': self.condition_details,
            'metrics': self.metrics,
            'summary': self.summary_text(),
        }

    def summary_text(self) -> str:
        """生成简短摘要"""
        signal_str = "✅" if self.is_signal else "❌"
        return f"{signal_str} {self.symbol} {self.strategy} {self.passed}/{self.total} Score:{self.score}"

    @classmethod
    def from_db_row(cls, row: Dict) -> 'StrategyResult':
        """从数据库行还原"""
        conditions = row.get('conditions', {})
        if isinstance(conditions, str):
            conditions = json.loads(conditions)
        details = row.get('condition_details', {})
        if isinstance(details, str):
            details = json.loads(details)
        metrics = row.get('metrics', {})
        if isinstance(metrics, str):
            metrics = json.loads(metrics)

        return cls(
            symbol=row['symbol'],
            name=metrics.get('name', row['symbol']),
            sector=metrics.get('sector', ''),
            price=metrics.get('price', 0),
            date=row['date'],
            strategy=row['strategy'],
            is_signal=bool(row.get('is_signal', 0)),
            score=row.get('score', 0),
            passed=row.get('passed', 0),
            total=row.get('total', 0),
            conditions=conditions,
            condition_details=details,
            metrics=metrics,
        )


# ============================================================
# Stage 2 结果
# ============================================================
@dataclass
class Stage2Result(StrategyResult):
    """Stage 2 分析结果"""
    strategy: str = "stage2"
    # Stage 2 特有字段（存在 metrics 里）
    sma50: float = 0
    sma150: float = 0
    sma200: float = 0
    week52_high: float = 0
    week52_low: float = 0
    pct_from_high: float = 0
    pct_from_low: float = 0
    pct_above_sma200: float = 0
    pct_above_sma50: float = 0
    trend_power: int = 0
    vol_signal: str = ""
    stock_return_6m: Optional[float] = None
    spy_return_6m: Optional[float] = None
    chg_5d: Optional[float] = None
    chg_20d: Optional[float] = None
    sma50_slope: Optional[float] = None

    def to_db_dict(self) -> Dict:
        base = super().to_db_dict()
        # 将 Stage2 特有字段打包进 metrics
        base['metrics'] = {
            'name': self.name,
            'sector': self.sector,
            'price': self.price,
            'sma50': self.sma50,
            'sma150': self.sma150,
            'sma200': self.sma200,
            'week52_high': self.week52_high,
            'week52_low': self.week52_low,
            'pct_from_high': self.pct_from_high,
            'pct_from_low': self.pct_from_low,
            'pct_above_sma200': self.pct_above_sma200,
            'pct_above_sma50': self.pct_above_sma50,
            'trend_power': self.trend_power,
            'vol_signal': self.vol_signal,
            'stock_return_6m': self.stock_return_6m,
            'spy_return_6m': self.spy_return_6m,
            'chg_5d': self.chg_5d,
            'chg_20d': self.chg_20d,
            'sma50_slope': self.sma50_slope,
        }
        return base


# ============================================================
# VCP 结果
# ============================================================
@dataclass
class VCPResult(StrategyResult):
    """VCP 分析结果"""
    strategy: str = "vcp"
    vcp_score: int = 0
    days_in_stage2: int = 0
    entry_price: Optional[float] = None
    week52_high: float = 0
    week52_low: float = 0
    sma50: float = 0
    sma150: Optional[float] = None
    sma10: float = 0
    chg_5d: Optional[float] = None
    chg_20d: Optional[float] = None

    def to_db_dict(self) -> Dict:
        base = super().to_db_dict()
        base['metrics'] = {
            'name': self.name,
            'sector': self.sector,
            'price': self.price,
            'vcp_score': self.vcp_score,
            'days_in_stage2': self.days_in_stage2,
            'entry_price': self.entry_price,
            'week52_high': self.week52_high,
            'week52_low': self.week52_low,
            'sma50': self.sma50,
            'sma150': self.sma150,
            'sma10': self.sma10,
            'chg_5d': self.chg_5d,
            'chg_20d': self.chg_20d,
            **self.metrics,  # 保留原始 metrics（bbw, vol_ratio 等）
        }
        return base


# ============================================================
# Bottom Fisher 结果
# ============================================================
@dataclass
class BottomFisherResult(StrategyResult):
    """Bottom Fisher 分析结果"""
    strategy: str = "bottom_fisher"
    bf_score: int = 0
    bonuses: Dict[str, bool] = field(default_factory=dict)
    week52_high: float = 0
    week52_low: float = 0
    sma50: Optional[float] = None
    sma200: Optional[float] = None
    sma10: Optional[float] = None
    chg_5d: Optional[float] = None
    chg_20d: Optional[float] = None

    def to_db_dict(self) -> Dict:
        base = super().to_db_dict()
        base['metrics'] = {
            'name': self.name,
            'sector': self.sector,
            'price': self.price,
            'bf_score': self.bf_score,
            'bonuses': self.bonuses,
            'week52_high': self.week52_high,
            'week52_low': self.week52_low,
            'sma50': self.sma50,
            'sma200': self.sma200,
            'sma10': self.sma10,
            'chg_5d': self.chg_5d,
            'chg_20d': self.chg_20d,
            **self.metrics,
        }
        return base


# ============================================================
# Market Pulse 结果
# ============================================================
@dataclass
class MarketPulseResult:
    """Market Pulse 分析结果（市场级别，非个股）"""
    date: str
    regime: str  # 'bullish' | 'neutral' | 'cautious' | 'bearish'
    composite_score: float
    component_scores: Dict[str, float] = field(default_factory=dict)
    spy_price: Optional[float] = None
    vix_value: Optional[float] = None
    index_data: Dict[str, Any] = field(default_factory=dict)
    breadth_data: Dict[str, Any] = field(default_factory=dict)
    regime_info: tuple = field(default_factory=tuple)  # (regime, emoji, label, hint)

    def to_db_dict(self) -> Dict:
        return {
            'date': self.date,
            'regime': self.regime,
            'composite_score': self.composite_score,
            'component_scores': self.component_scores,
            'spy_price': self.spy_price,
            'vix_value': self.vix_value,
            'index_data': self.index_data,
            'breadth_data': self.breadth_data,
        }


# ============================================================
# 信号变化
# ============================================================
@dataclass
class SignalChange:
    """信号状态变化事件"""
    symbol: str
    date: str
    strategy: str
    change_type: str  # 'entry' | 'exit' | 'new_signal' | 'lost_signal'
    price: Optional[float] = None
    score: Optional[float] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def to_db_dict(self) -> Dict:
        return {
            'symbol': self.symbol,
            'date': self.date,
            'strategy': self.strategy,
            'change_type': self.change_type,
            'price': self.price,
            'score': self.score,
            'details': self.details,
        }
