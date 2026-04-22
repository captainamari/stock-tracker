"""
Stock Tracker — SQLite 数据访问层
统一的数据库接口，供所有策略脚本和 Web 层共享。

设计原则：
  - 单一 SQLite 文件，零外部依赖
  - 所有数据库操作集中在此模块
  - 策略特定的指标使用 JSON 列存储，保持灵活性
  - 线程安全：每次操作独立获取连接
"""

import sqlite3
import json
import os
import sys
import io
from datetime import datetime, date
from pathlib import Path
from contextlib import contextmanager
from typing import Optional, List, Dict, Any, Tuple

# Cross-platform UTF-8 output fix (Windows GBK terminals)
try:
    from lib.encoding_fix import ensure_utf8_output
except ImportError:
    try:
        from encoding_fix import ensure_utf8_output
    except ImportError:
        def ensure_utf8_output():
            if sys.stdout and hasattr(sys.stdout, 'buffer'):
                if sys.stdout.encoding and sys.stdout.encoding.lower().replace('-', '') != 'utf8':
                    sys.stdout = io.TextIOWrapper(
                        sys.stdout.buffer, encoding='utf-8', errors='replace',
                        line_buffering=sys.stdout.line_buffering,
                    )
            if sys.stderr and hasattr(sys.stderr, 'buffer'):
                if sys.stderr.encoding and sys.stderr.encoding.lower().replace('-', '') != 'utf8':
                    sys.stderr = io.TextIOWrapper(
                        sys.stderr.buffer, encoding='utf-8', errors='replace',
                        line_buffering=sys.stderr.line_buffering,
                    )
ensure_utf8_output()


# ============================================================
# JSON 辅助 — 处理 numpy 类型
# ============================================================
class _NumpyEncoder(json.JSONEncoder):
    """处理 numpy 类型的 JSON 编码器，避免序列化错误"""
    def default(self, obj):
        try:
            import numpy as np
            if isinstance(obj, (np.bool_,)):
                return bool(obj)
            if isinstance(obj, (np.integer,)):
                return int(obj)
            if isinstance(obj, (np.floating,)):
                if np.isnan(obj) or np.isinf(obj):
                    return None
                return float(obj)
            if isinstance(obj, np.ndarray):
                return obj.tolist()
        except ImportError:
            pass
        return super().default(obj)


def _json_dumps(obj) -> str:
    """统一的 JSON 序列化，自动处理 numpy 类型"""
    return json.dumps(obj, ensure_ascii=False, cls=_NumpyEncoder)

# 数据库文件位置
DB_DIR = Path(__file__).parent.parent / "data"
DB_PATH = DB_DIR / "stock_tracker.db"


# ============================================================
# Schema 定义
# ============================================================
SCHEMA_SQL = """
-- 观察列表：同步自 tickers.json
CREATE TABLE IF NOT EXISTS watchlist (
    symbol          TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    sector          TEXT DEFAULT '',
    source_type     TEXT DEFAULT 'monitored',   -- 'monitored' | 'yfinance_only'
    yf_ticker       TEXT,                        -- yfinance 特殊 ticker (如 ^VIX)
    enabled         INTEGER DEFAULT 1,
    added_at        TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

-- 日线价格：OHLCV
CREATE TABLE IF NOT EXISTS stock_prices (
    symbol          TEXT NOT NULL,
    date            TEXT NOT NULL,               -- YYYY-MM-DD
    open            REAL,
    high            REAL,
    low             REAL,
    close           REAL NOT NULL,
    volume          INTEGER DEFAULT 0,
    PRIMARY KEY (symbol, date)
);
CREATE INDEX IF NOT EXISTS idx_prices_date ON stock_prices(date);
CREATE INDEX IF NOT EXISTS idx_prices_symbol ON stock_prices(symbol);

-- 策略计算结果：统一存储所有策略的每日计算数据
-- 使用 JSON 列存储策略特定的指标，避免为每个策略建独立表
CREATE TABLE IF NOT EXISTS strategy_results (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol          TEXT NOT NULL,
    date            TEXT NOT NULL,               -- YYYY-MM-DD
    strategy        TEXT NOT NULL,               -- 'stage2' | 'vcp' | 'bottom_fisher' | 'buying_checklist' | 'market_pulse'
    is_signal       INTEGER DEFAULT 0,           -- 是否触发信号
    score           REAL DEFAULT 0,              -- 策略评分 (0-100)
    passed          INTEGER DEFAULT 0,           -- 满足条件数
    total           INTEGER DEFAULT 0,           -- 总条件数
    conditions      TEXT DEFAULT '{}',           -- JSON: {C1: true, C2: false, ...}
    condition_details TEXT DEFAULT '{}',         -- JSON: {C1: "诊断文本", ...}
    metrics         TEXT DEFAULT '{}',           -- JSON: 策略特定的计算指标
    summary         TEXT DEFAULT '',             -- 简短摘要文本
    created_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(symbol, date, strategy)
);
CREATE INDEX IF NOT EXISTS idx_results_strategy ON strategy_results(strategy, date);
CREATE INDEX IF NOT EXISTS idx_results_symbol_date ON strategy_results(symbol, date);

-- 策略状态：每个策略的当前状态跟踪（替代 state/*.json）
CREATE TABLE IF NOT EXISTS strategy_states (
    symbol          TEXT NOT NULL,
    strategy        TEXT NOT NULL,               -- 'stage2' | 'vcp' | 'bottom_fisher' | 'buying_checklist'
    is_active       INTEGER DEFAULT 0,           -- 当前是否处于活跃信号状态
    entry_date      TEXT,                        -- 首次进入信号的日期
    entry_price     REAL,                        -- 进入时的价格
    extra           TEXT DEFAULT '{}',           -- JSON: 策略特定的状态数据
    updated_at      TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (symbol, strategy)
);

-- 信号变化历史：记录每次信号进出
CREATE TABLE IF NOT EXISTS signal_changes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol          TEXT NOT NULL,
    date            TEXT NOT NULL,
    strategy        TEXT NOT NULL,
    change_type     TEXT NOT NULL,               -- 'entry' | 'exit' | 'new_signal' | 'lost_signal'
    price           REAL,
    score           REAL,
    details         TEXT DEFAULT '{}',           -- JSON: 变化详情
    created_at      TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_changes_date ON signal_changes(date);
CREATE INDEX IF NOT EXISTS idx_changes_strategy ON signal_changes(strategy, date);

-- Market Pulse：市场宏观状态（独立于个股）
CREATE TABLE IF NOT EXISTS market_pulse (
    date            TEXT PRIMARY KEY,            -- YYYY-MM-DD
    regime          TEXT NOT NULL,               -- 'bullish' | 'neutral' | 'cautious' | 'bearish'
    composite_score REAL NOT NULL,               -- 0-100
    component_scores TEXT DEFAULT '{}',          -- JSON: {SPY: 87, QQQ: 95, ...}
    spy_price       REAL,
    vix_value       REAL,
    index_data      TEXT DEFAULT '{}',           -- JSON: SPY/QQQ/IWM 详细分析数据
    breadth_data    TEXT DEFAULT '{}',           -- JSON: 内部宽度数据
    distribution_days TEXT DEFAULT '{}',         -- JSON: Distribution Day data {SPY: {...}, QQQ: {...}}
    created_at      TEXT DEFAULT (datetime('now'))
);

-- Pipeline 执行记录：每次 daily_pipeline 的各步骤状态
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date        TEXT NOT NULL,               -- YYYY-MM-DD
    strategy        TEXT NOT NULL,               -- 'prices' | 'market_pulse' | 'stage2' | 'vcp' | 'bottom_fisher' | 'buying_checklist'
    status          TEXT NOT NULL,               -- 'ok' | 'failed' | 'skipped' | 'running'
    error_msg       TEXT,
    duration        REAL,                        -- 执行耗时（秒）
    created_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(run_date, strategy)
);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_date ON pipeline_runs(run_date);

-- 通知推送记录：Telegram 推送的幂等日志
CREATE TABLE IF NOT EXISTS notification_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    notify_date     TEXT NOT NULL,               -- YYYY-MM-DD
    channel         TEXT NOT NULL,               -- 'telegram'
    strategy        TEXT NOT NULL,               -- 'market_pulse' | 'stage2' | ... | 'daily_summary'
    status          TEXT NOT NULL,               -- 'sent' | 'failed' | 'skipped'
    message_id      TEXT,                        -- Telegram message ID（用于后续编辑/删除）
    error_msg       TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(notify_date, channel, strategy)
);
CREATE INDEX IF NOT EXISTS idx_notification_date ON notification_log(notify_date);

-- 数据库版本追踪
CREATE TABLE IF NOT EXISTS db_meta (
    key             TEXT PRIMARY KEY,
    value           TEXT NOT NULL,
    updated_at      TEXT DEFAULT (datetime('now'))
);
"""

DB_VERSION = "1.1.0"


# ============================================================
# 连接管理
# ============================================================
def _ensure_dir():
    """确保数据库目录存在"""
    DB_DIR.mkdir(parents=True, exist_ok=True)


def get_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """
    获取数据库连接。
    - 启用 WAL 模式提升并发读性能
    - 启用外键约束
    - 返回 Row 对象以便按列名访问
    """
    path = db_path or DB_PATH
    _ensure_dir()
    conn = sqlite3.connect(str(path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


@contextmanager
def get_db(db_path: Optional[Path] = None):
    """
    数据库连接的上下文管理器。
    自动提交或回滚事务。

    用法:
        with get_db() as conn:
            conn.execute("INSERT INTO ...")
    """
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Optional[Path] = None):
    """
    初始化数据库：创建所有表和索引。
    幂等操作，可安全重复调用。
    """
    with get_db(db_path) as conn:
        conn.executescript(SCHEMA_SQL)

        # Migration: add distribution_days column if missing (v1.2.0)
        try:
            cols = [row[1] for row in conn.execute("PRAGMA table_info(market_pulse)").fetchall()]
            if 'distribution_days' not in cols:
                conn.execute("ALTER TABLE market_pulse ADD COLUMN distribution_days TEXT DEFAULT '{}'")
                print("  📦 Migration: added distribution_days column to market_pulse")
        except Exception:
            pass  # column already exists or table not yet created

        # 记录数据库版本
        conn.execute(
            "INSERT OR REPLACE INTO db_meta (key, value, updated_at) VALUES (?, ?, ?)",
            ("version", DB_VERSION, datetime.now().isoformat())
        )
    print(f"✅ 数据库已初始化: {db_path or DB_PATH}")


# ============================================================
# Watchlist (观察列表)
# ============================================================
def upsert_watchlist(symbols: List[Dict[str, Any]], db_path: Optional[Path] = None):
    """
    批量更新观察列表。
    每个 dict 需包含: symbol, name, sector, enabled
    可选: source_type, yf_ticker
    """
    with get_db(db_path) as conn:
        for s in symbols:
            conn.execute("""
                INSERT INTO watchlist (symbol, name, sector, source_type, yf_ticker, enabled, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    name = excluded.name,
                    sector = excluded.sector,
                    source_type = excluded.source_type,
                    yf_ticker = excluded.yf_ticker,
                    enabled = excluded.enabled,
                    updated_at = excluded.updated_at
            """, (
                s['symbol'],
                s.get('name', s['symbol']),
                s.get('sector', ''),
                s.get('source_type', 'monitored'),
                s.get('yf_ticker'),
                1 if s.get('enabled', True) else 0,
                datetime.now().isoformat(),
            ))


def get_watchlist(enabled_only: bool = True, source_type: Optional[str] = None,
                  db_path: Optional[Path] = None) -> List[Dict]:
    """获取观察列表"""
    with get_db(db_path) as conn:
        sql = "SELECT * FROM watchlist WHERE 1=1"
        params = []
        if enabled_only:
            sql += " AND enabled = 1"
        if source_type:
            sql += " AND source_type = ?"
            params.append(source_type)
        sql += " ORDER BY symbol"
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def get_watchlist_item(symbol: str, db_path: Optional[Path] = None) -> Optional[Dict]:
    """
    获取单个 watchlist 条目（不论 enabled 状态）。
    用于检查 ticker 是否曾经存在于 watchlist 中。
    """
    with get_db(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM watchlist WHERE symbol = ?", (symbol,)
        ).fetchone()
        return dict(row) if row else None


def set_ticker_enabled(symbol: str, enabled: bool, db_path: Optional[Path] = None):
    """
    设置 ticker 的 enabled 状态（软删除/恢复）。
    """
    with get_db(db_path) as conn:
        conn.execute(
            "UPDATE watchlist SET enabled = ?, updated_at = ? WHERE symbol = ?",
            (1 if enabled else 0, datetime.now().isoformat(), symbol)
        )


# ============================================================
# Stock Prices (价格数据)
# ============================================================
def upsert_prices(symbol: str, rows: List[Dict[str, Any]], db_path: Optional[Path] = None):
    """
    批量写入价格数据（UPSERT）。
    每个 dict 需包含: date, open, high, low, close, volume
    """
    with get_db(db_path) as conn:
        conn.executemany("""
            INSERT INTO stock_prices (symbol, date, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, date) DO UPDATE SET
                open = excluded.open,
                high = excluded.high,
                low = excluded.low,
                close = excluded.close,
                volume = excluded.volume
        """, [
            (
                symbol,
                r['date'] if isinstance(r['date'], str) else r['date'].strftime('%Y-%m-%d'),
                float(r.get('open', 0)),
                float(r.get('high', 0)),
                float(r.get('low', 0)),
                float(r['close']),
                int(r.get('volume', 0)),
            )
            for r in rows
        ])


def get_prices(symbol: str, start_date: Optional[str] = None, end_date: Optional[str] = None,
               limit: Optional[int] = None, db_path: Optional[Path] = None) -> List[Dict]:
    """
    查询价格数据。
    返回按日期升序排列的列表。
    """
    with get_db(db_path) as conn:
        sql = "SELECT * FROM stock_prices WHERE symbol = ?"
        params: list = [symbol]
        if start_date:
            sql += " AND date >= ?"
            params.append(start_date)
        if end_date:
            sql += " AND date <= ?"
            params.append(end_date)
        sql += " ORDER BY date ASC"
        if limit:
            sql += " LIMIT ?"
            params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def get_latest_price_date(symbol: str, db_path: Optional[Path] = None) -> Optional[str]:
    """获取某只股票最新的价格日期"""
    with get_db(db_path) as conn:
        row = conn.execute(
            "SELECT MAX(date) as latest FROM stock_prices WHERE symbol = ?",
            (symbol,)
        ).fetchone()
        return row['latest'] if row and row['latest'] else None


def get_price_count(symbol: Optional[str] = None, db_path: Optional[Path] = None) -> int:
    """获取价格记录数"""
    with get_db(db_path) as conn:
        if symbol:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM stock_prices WHERE symbol = ?", (symbol,)
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) as cnt FROM stock_prices").fetchone()
        return row['cnt']


def get_all_symbols_with_prices(db_path: Optional[Path] = None) -> List[str]:
    """获取所有有价格数据的股票代码"""
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT DISTINCT symbol FROM stock_prices ORDER BY symbol"
        ).fetchall()
        return [r['symbol'] for r in rows]


# ============================================================
# Strategy Results (策略计算结果)
# ============================================================
def save_strategy_result(
    symbol: str,
    date_str: str,
    strategy: str,
    is_signal: bool,
    score: float,
    passed: int,
    total: int,
    conditions: Dict,
    condition_details: Dict,
    metrics: Dict,
    summary: str = "",
    db_path: Optional[Path] = None,
):
    """保存单条策略计算结果"""
    with get_db(db_path) as conn:
        conn.execute("""
            INSERT INTO strategy_results
                (symbol, date, strategy, is_signal, score, passed, total,
                 conditions, condition_details, metrics, summary)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, date, strategy) DO UPDATE SET
                is_signal = excluded.is_signal,
                score = excluded.score,
                passed = excluded.passed,
                total = excluded.total,
                conditions = excluded.conditions,
                condition_details = excluded.condition_details,
                metrics = excluded.metrics,
                summary = excluded.summary,
                created_at = datetime('now')
        """, (
            symbol, date_str, strategy,
            1 if is_signal else 0,
            score, passed, total,
            _json_dumps(conditions),
            _json_dumps(condition_details),
            _json_dumps(metrics),
            summary,
        ))


def save_strategy_results_batch(results: List[Dict], strategy: str,
                                date_str: str, db_path: Optional[Path] = None):
    """
    批量保存策略结果。
    每个 result dict 需包含: symbol, is_signal, score, passed, total,
                             conditions, condition_details, metrics
    """
    with get_db(db_path) as conn:
        conn.executemany("""
            INSERT INTO strategy_results
                (symbol, date, strategy, is_signal, score, passed, total,
                 conditions, condition_details, metrics, summary)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, date, strategy) DO UPDATE SET
                is_signal = excluded.is_signal,
                score = excluded.score,
                passed = excluded.passed,
                total = excluded.total,
                conditions = excluded.conditions,
                condition_details = excluded.condition_details,
                metrics = excluded.metrics,
                summary = excluded.summary,
                created_at = datetime('now')
        """, [
            (
                r['symbol'], date_str, strategy,
                1 if r.get('is_signal', False) else 0,
                r.get('score', 0),
                r.get('passed', 0),
                r.get('total', 0),
                _json_dumps(r.get('conditions', {})),
                _json_dumps(r.get('condition_details', {})),
                _json_dumps(r.get('metrics', {})),
                r.get('summary', ''),
            )
            for r in results
        ])


def get_strategy_results(
    strategy: str,
    date_str: Optional[str] = None,
    symbol: Optional[str] = None,
    signal_only: bool = False,
    limit: int = 100,
    db_path: Optional[Path] = None,
) -> List[Dict]:
    """
    查询策略结果。
    返回的 conditions/condition_details/metrics 已解析为 dict。
    """
    with get_db(db_path) as conn:
        sql = "SELECT * FROM strategy_results WHERE strategy = ?"
        params: list = [strategy]
        if date_str:
            sql += " AND date = ?"
            params.append(date_str)
        if symbol:
            sql += " AND symbol = ?"
            params.append(symbol)
        if signal_only:
            sql += " AND is_signal = 1"
        sql += " ORDER BY date DESC, score DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d['conditions'] = json.loads(d['conditions']) if d['conditions'] else {}
            d['condition_details'] = json.loads(d['condition_details']) if d['condition_details'] else {}
            d['metrics'] = json.loads(d['metrics']) if d['metrics'] else {}
            results.append(d)
        return results


def get_strategy_history(symbol: str, strategy: str, days: int = 30,
                         db_path: Optional[Path] = None) -> List[Dict]:
    """获取某只股票某策略的历史计算数据"""
    with get_db(db_path) as conn:
        rows = conn.execute("""
            SELECT * FROM strategy_results
            WHERE symbol = ? AND strategy = ?
            ORDER BY date DESC LIMIT ?
        """, (symbol, strategy, days)).fetchall()

        results = []
        for r in rows:
            d = dict(r)
            d['conditions'] = json.loads(d['conditions']) if d['conditions'] else {}
            d['condition_details'] = json.loads(d['condition_details']) if d['condition_details'] else {}
            d['metrics'] = json.loads(d['metrics']) if d['metrics'] else {}
            results.append(d)
        return results


# ============================================================
# Strategy States (策略状态)
# ============================================================
def upsert_strategy_state(
    symbol: str,
    strategy: str,
    is_active: bool,
    entry_date: Optional[str] = None,
    entry_price: Optional[float] = None,
    extra: Optional[Dict] = None,
    db_path: Optional[Path] = None,
):
    """更新策略状态"""
    with get_db(db_path) as conn:
        conn.execute("""
            INSERT INTO strategy_states (symbol, strategy, is_active, entry_date, entry_price, extra, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, strategy) DO UPDATE SET
                is_active = excluded.is_active,
                entry_date = excluded.entry_date,
                entry_price = excluded.entry_price,
                extra = excluded.extra,
                updated_at = excluded.updated_at
        """, (
            symbol, strategy,
            1 if is_active else 0,
            entry_date, entry_price,
            _json_dumps(extra or {}),
            datetime.now().isoformat(),
        ))





def upsert_strategy_states_batch(states: List[Dict], strategy: str,
                                 db_path: Optional[Path] = None):
    """
    批量更新策略状态。
    每个 dict: {symbol, is_active, entry_date?, entry_price?, extra?}
    """
    with get_db(db_path) as conn:
        conn.executemany("""
            INSERT INTO strategy_states (symbol, strategy, is_active, entry_date, entry_price, extra, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, strategy) DO UPDATE SET
                is_active = excluded.is_active,
                entry_date = excluded.entry_date,
                entry_price = excluded.entry_price,
                extra = excluded.extra,
                updated_at = excluded.updated_at
        """, [
            (
                s['symbol'], strategy,
                1 if s.get('is_active', False) else 0,
                s.get('entry_date'),
                s.get('entry_price'),
                _json_dumps(s.get('extra', {})),
                datetime.now().isoformat(),
            )
            for s in states
        ])


def get_strategy_states(strategy: str, active_only: bool = False,
                        db_path: Optional[Path] = None) -> List[Dict]:
    """获取某策略的所有状态"""
    with get_db(db_path) as conn:
        sql = "SELECT * FROM strategy_states WHERE strategy = ?"
        params: list = [strategy]
        if active_only:
            sql += " AND is_active = 1"
        sql += " ORDER BY symbol"
        rows = conn.execute(sql, params).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d['extra'] = json.loads(d['extra']) if d['extra'] else {}
            results.append(d)
        return results


def get_strategy_state(symbol: str, strategy: str,
                       db_path: Optional[Path] = None) -> Optional[Dict]:
    """获取单个策略状态"""
    with get_db(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM strategy_states WHERE symbol = ? AND strategy = ?",
            (symbol, strategy)
        ).fetchone()
        if row:
            d = dict(row)
            d['extra'] = json.loads(d['extra']) if d['extra'] else {}
            return d
        return None


# ============================================================
# Signal Changes (信号变化历史)
# ============================================================
def record_signal_change(
    symbol: str,
    date_str: str,
    strategy: str,
    change_type: str,
    price: Optional[float] = None,
    score: Optional[float] = None,
    details: Optional[Dict] = None,
    db_path: Optional[Path] = None,
):
    """记录一次信号变化"""
    with get_db(db_path) as conn:
        conn.execute("""
            INSERT INTO signal_changes (symbol, date, strategy, change_type, price, score, details)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            symbol, date_str, strategy, change_type,
            price, score,
            _json_dumps(details or {}),
        ))


def get_signal_changes(strategy: Optional[str] = None, date_str: Optional[str] = None,
                       symbol: Optional[str] = None, limit: int = 50,
                       db_path: Optional[Path] = None) -> List[Dict]:
    """查询信号变化历史"""
    with get_db(db_path) as conn:
        sql = "SELECT * FROM signal_changes WHERE 1=1"
        params: list = []
        if strategy:
            sql += " AND strategy = ?"
            params.append(strategy)
        if date_str:
            sql += " AND date = ?"
            params.append(date_str)
        if symbol:
            sql += " AND symbol = ?"
            params.append(symbol)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d['details'] = json.loads(d['details']) if d['details'] else {}
            results.append(d)
        return results


# ============================================================
# Market Pulse (市场宏观状态)
# ============================================================
def save_market_pulse(
    date_str: str,
    regime: str,
    composite_score: float,
    component_scores: Dict,
    spy_price: Optional[float] = None,
    vix_value: Optional[float] = None,
    index_data: Optional[Dict] = None,
    breadth_data: Optional[Dict] = None,
    distribution_days: Optional[Dict] = None,
    db_path: Optional[Path] = None,
):
    """保存 Market Pulse 数据"""
    with get_db(db_path) as conn:
        conn.execute("""
            INSERT INTO market_pulse
                (date, regime, composite_score, component_scores,
                 spy_price, vix_value, index_data, breadth_data, distribution_days)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                regime = excluded.regime,
                composite_score = excluded.composite_score,
                component_scores = excluded.component_scores,
                spy_price = excluded.spy_price,
                vix_value = excluded.vix_value,
                index_data = excluded.index_data,
                breadth_data = excluded.breadth_data,
                distribution_days = excluded.distribution_days,
                created_at = datetime('now')
        """, (
            date_str, regime, composite_score,
            _json_dumps(component_scores),
            spy_price, vix_value,
            _json_dumps(index_data or {}),
            _json_dumps(breadth_data or {}),
            _json_dumps(distribution_days or {}),
        ))


def get_market_pulse(date_str: Optional[str] = None, limit: int = 30,
                     db_path: Optional[Path] = None) -> List[Dict]:
    """查询 Market Pulse 历史"""
    with get_db(db_path) as conn:
        if date_str:
            rows = conn.execute(
                "SELECT * FROM market_pulse WHERE date = ?", (date_str,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM market_pulse ORDER BY date DESC LIMIT ?", (limit,)
            ).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d['component_scores'] = json.loads(d['component_scores']) if d['component_scores'] else {}
            d['index_data'] = json.loads(d['index_data']) if d['index_data'] else {}
            d['breadth_data'] = json.loads(d['breadth_data']) if d['breadth_data'] else {}
            d['distribution_days'] = json.loads(d.get('distribution_days') or '{}')
            results.append(d)
        return results


def get_latest_market_pulse(db_path: Optional[Path] = None) -> Optional[Dict]:
    """获取最新的 Market Pulse"""
    results = get_market_pulse(limit=1, db_path=db_path)
    return results[0] if results else None


# ============================================================
# 统计与诊断
# ============================================================
def get_db_stats(db_path: Optional[Path] = None) -> Dict:
    """获取数据库统计信息"""
    with get_db(db_path) as conn:
        stats = {}

        # 各表行数
        tables = ['watchlist', 'stock_prices', 'strategy_results',
                  'strategy_states', 'signal_changes', 'market_pulse']
        for table in tables:
            row = conn.execute(f"SELECT COUNT(*) as cnt FROM {table}").fetchone()
            stats[f'{table}_count'] = row['cnt']

        # 价格数据范围
        row = conn.execute(
            "SELECT MIN(date) as min_date, MAX(date) as max_date FROM stock_prices"
        ).fetchone()
        stats['price_date_range'] = f"{row['min_date']} ~ {row['max_date']}" if row['min_date'] else "N/A"

        # 不同股票数
        row = conn.execute(
            "SELECT COUNT(DISTINCT symbol) as cnt FROM stock_prices"
        ).fetchone()
        stats['symbols_with_prices'] = row['cnt']

        # 数据库文件大小
        db_file = db_path or DB_PATH
        if db_file.exists():
            size_mb = db_file.stat().st_size / (1024 * 1024)
            stats['db_size_mb'] = round(size_mb, 2)

        # 版本
        try:
            row = conn.execute(
                "SELECT value FROM db_meta WHERE key = 'version'"
            ).fetchone()
            stats['version'] = row['value'] if row else 'unknown'
        except Exception:
            stats['version'] = 'unknown'

        return stats


# ============================================================
# DataFrame 辅助 — 策略脚本使用
# ============================================================
def get_prices_as_dataframe(symbol: str, min_rows: int = 0,
                            db_path: Optional[Path] = None):
    """
    从数据库获取价格数据，返回 pandas DataFrame。
    格式兼容旧 CSV 缓存读取方式：
      - 索引: DatetimeIndex (tz-naive)
      - 列名: Open, High, Low, Close, Volume
    返回 None 如果数据不足。
    """
    try:
        import pandas as pd
    except ImportError:
        raise ImportError("pandas is required: pip install pandas")

    rows = get_prices(symbol, db_path=db_path)
    if not rows or len(rows) < min_rows:
        return None

    df = pd.DataFrame(rows)
    df['date'] = pd.to_datetime(df['date'])
    df.set_index('date', inplace=True)
    df.index.name = None

    # 列名与旧 CSV 格式对齐 (首字母大写)
    df.rename(columns={
        'open': 'Open', 'high': 'High', 'low': 'Low',
        'close': 'Close', 'volume': 'Volume',
    }, inplace=True)

    # 去掉 symbol 列
    df.drop(columns=['symbol'], inplace=True, errors='ignore')

    return df


# ============================================================
# Pipeline Runs (执行记录)
# ============================================================
def record_pipeline_run(
    run_date: str,
    strategy: str,
    status: str,
    error_msg: Optional[str] = None,
    duration: Optional[float] = None,
    db_path: Optional[Path] = None,
):
    """记录 pipeline 某步骤的执行状态（UPSERT）"""
    with get_db(db_path) as conn:
        conn.execute("""
            INSERT INTO pipeline_runs (run_date, strategy, status, error_msg, duration)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(run_date, strategy) DO UPDATE SET
                status = excluded.status,
                error_msg = excluded.error_msg,
                duration = excluded.duration,
                created_at = datetime('now')
        """, (run_date, strategy, status, error_msg, duration))


def get_pipeline_runs(run_date: str, db_path: Optional[Path] = None) -> List[Dict]:
    """获取某日所有 pipeline 步骤的执行记录"""
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM pipeline_runs WHERE run_date = ? ORDER BY id",
            (run_date,)
        ).fetchall()
        return [dict(r) for r in rows]


def is_pipeline_step_completed(run_date: str, strategy: str,
                               db_path: Optional[Path] = None) -> bool:
    """检查某步骤今日是否已成功完成"""
    with get_db(db_path) as conn:
        row = conn.execute(
            "SELECT status FROM pipeline_runs WHERE run_date = ? AND strategy = ?",
            (run_date, strategy)
        ).fetchone()
        return row is not None and row['status'] == 'ok'


# ============================================================
# Notification Log (推送记录)
# ============================================================
def record_notification(
    notify_date: str,
    channel: str,
    strategy: str,
    status: str,
    message_id: Optional[str] = None,
    error_msg: Optional[str] = None,
    db_path: Optional[Path] = None,
):
    """记录推送结果（UPSERT）"""
    with get_db(db_path) as conn:
        conn.execute("""
            INSERT INTO notification_log
                (notify_date, channel, strategy, status, message_id, error_msg)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(notify_date, channel, strategy) DO UPDATE SET
                status = excluded.status,
                message_id = excluded.message_id,
                error_msg = excluded.error_msg,
                created_at = datetime('now')
        """, (notify_date, channel, strategy, status, message_id, error_msg))


def is_notification_sent(notify_date: str, strategy: str,
                         channel: str = 'telegram',
                         db_path: Optional[Path] = None) -> bool:
    """检查今日某策略是否已成功推送（幂等检查）"""
    with get_db(db_path) as conn:
        row = conn.execute(
            "SELECT status FROM notification_log WHERE notify_date = ? AND channel = ? AND strategy = ?",
            (notify_date, channel, strategy)
        ).fetchone()
        return row is not None and row['status'] == 'sent'


def get_notification_log(notify_date: str, channel: str = 'telegram',
                         db_path: Optional[Path] = None) -> List[Dict]:
    """获取某日所有推送记录"""
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM notification_log WHERE notify_date = ? AND channel = ? ORDER BY id",
            (notify_date, channel)
        ).fetchall()
        return [dict(r) for r in rows]


# ============================================================
# CLI 入口
# ============================================================
if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "init":
        init_db()
    elif len(sys.argv) > 1 and sys.argv[1] == "stats":
        init_db()  # 确保表存在
        stats = get_db_stats()
        print("\n📊 数据库统计:")
        for k, v in stats.items():
            print(f"  {k}: {v}")
    else:
        print("用法:")
        print("  python -m lib.db init   — 初始化数据库")
        print("  python -m lib.db stats  — 查看统计信息")
