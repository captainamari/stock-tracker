#!/usr/bin/env python3
"""
收盘价抓取脚本 v2.0 - yfinance 数据源
唯一数据采集脚本，覆盖所有监控股票（个股 + 指数/ETF）

v2.0 变更：
  - 数据写入 SQLite DB（主存储）
  - CSV 文件仅作备用缓存保留
  - 使用 lib.config 加载 ticker 配置
  - 使用 lib.db 写入价格数据

数据来源: Yahoo Finance (via yfinance)

注意: 原 save_prices.py (Stooq 数据源) 已于 2026-04 停用，
      stooq.com 不再提供免费数据 API。该文件保留但不再使用。
"""

import sys
import time
import random
import csv
import argparse
from datetime import datetime, timedelta
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from lib.encoding_fix import ensure_utf8_output
ensure_utf8_output()

from lib.db import init_db, upsert_prices, get_price_count, get_latest_price_date
from lib.config import load_config, parse_tickers, sync_watchlist

# 路径
DATA_DIR = PROJECT_ROOT / "data" / "prices"
LOGS_DIR = PROJECT_ROOT / "logs"
LOG_FILE = LOGS_DIR / "save_prices_yfinance.log"

# yfinance 请求参数 - 适当间隔，避免被限流
REQUEST_DELAY = 2.0
MAX_RETRIES = 3


def log(message, level="INFO"):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    entry = f"[{timestamp}] [{level}] {message}"
    print(entry)
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(entry + '\n')
    except Exception:
        pass


def build_ticker_list(config, mode='all'):
    """
    从配置构建 ticker 列表
    mode='all'           -> monitored + yfinance_only + benchmark
    mode='yfinance_only' -> 仅 yfinance_only 列表
    """
    tickers_info = parse_tickers(config)
    result = []
    seen = set()

    # yfinance_only 列表（如 ^VIX 等特殊 ticker）
    for t in tickers_info:
        if t.source_type == 'yfinance_only' and t.enabled:
            result.append({
                'symbol': t.symbol,
                'yf_ticker': t.yf_ticker or t.symbol,
            })
            seen.add(t.symbol)

    if mode == 'yfinance_only':
        return result

    # monitored 列表（普通美股，yf_ticker 与 symbol 相同）
    for t in tickers_info:
        if t.source_type == 'monitored' and t.enabled and t.symbol not in seen:
            result.append({
                'symbol': t.symbol,
                'yf_ticker': t.yf_ticker or t.symbol,
            })
            seen.add(t.symbol)

    # benchmark
    benchmark = config.get('benchmark', 'SPY')
    if benchmark not in seen:
        result.append({
            'symbol': benchmark,
            'yf_ticker': benchmark,
        })

    return result


def fetch_yfinance(yf_ticker, days=365, retries=MAX_RETRIES):
    """
    从 yfinance 拉取历史数据
    返回: list of dict [{Date, Open, High, Low, Close, Volume}, ...]
    """
    try:
        import yfinance as yf
    except ImportError:
        log("yfinance 未安装，请运行: pip install yfinance", "ERROR")
        return None

    import math

    end = datetime.today()
    start = end - timedelta(days=days)

    for attempt in range(retries):
        try:
            ticker_obj = yf.Ticker(yf_ticker)

            # 先尝试 auto_adjust=True（调整后价格）
            df = ticker_obj.history(
                start=start.strftime('%Y-%m-%d'),
                end=end.strftime('%Y-%m-%d'),
                auto_adjust=True,
            )

            if df is not None and not df.empty:
                last_close = df['Close'].iloc[-1]
                if math.isnan(last_close):
                    log(f"{yf_ticker} auto_adjust=True 最新行 Close=NaN，回退到 auto_adjust=False", "WARNING")
                    df = ticker_obj.history(
                        start=start.strftime('%Y-%m-%d'),
                        end=end.strftime('%Y-%m-%d'),
                        auto_adjust=False,
                    )

            if df is None or df.empty:
                log(f"{yf_ticker} yfinance 无数据返回", "WARNING")
                return None

            rows = []
            for idx, row in df.iterrows():
                try:
                    date_str = idx.strftime('%Y-%m-%d')
                    o = float(row['Open'])
                    h = float(row['High'])
                    l = float(row['Low'])
                    c = float(row['Close'])

                    if math.isnan(o) or math.isnan(h) or math.isnan(l) or math.isnan(c):
                        log(f"{yf_ticker} 跳过 NaN 行: {date_str}", "WARNING")
                        continue

                    rows.append({
                        'Date': date_str,
                        'Open': f"{o:.4f}",
                        'High': f"{h:.4f}",
                        'Low': f"{l:.4f}",
                        'Close': f"{c:.4f}",
                        'Volume': str(int(float(row.get('Volume', 0) or 0))),
                    })
                except (ValueError, KeyError) as e:
                    log(f"{yf_ticker} 跳过异常行 {idx}: {e}", "WARNING")
                    continue

            if rows:
                rows.sort(key=lambda r: r['Date'])
                return rows

        except Exception as e:
            if attempt < retries - 1:
                wait = 5 + random.uniform(2, 5)
                log(f"{yf_ticker} 第 {attempt+1} 次失败 ({e})，{wait:.1f}s 后重试...", "WARNING")
                time.sleep(wait)
            else:
                log(f"{yf_ticker} 拉取失败（已重试 {retries} 次）: {e}", "ERROR")

    return None


def save_to_db(symbol, rows):
    """将价格数据写入 SQLite DB"""
    db_rows = [
        {
            'date': r['Date'],
            'open': float(r['Open']),
            'high': float(r['High']),
            'low': float(r['Low']),
            'close': float(r['Close']),
            'volume': int(r['Volume']),
        }
        for r in rows
    ]
    upsert_prices(symbol, db_rows)


def save_csv(symbol, rows):
    """写回完整 CSV 作为备用缓存"""
    cache_file = DATA_DIR / f"{symbol}.csv"
    rows_sorted = sorted(rows, key=lambda r: r['Date'])
    fieldnames = ['Date', 'Open', 'High', 'Low', 'Close', 'Volume']
    with open(cache_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows_sorted)


def parse_args():
    parser = argparse.ArgumentParser(description="save_prices_yfinance v2.0 — Yahoo Finance 数据源")
    parser.add_argument('--mode', type=str, default='all', choices=['all', 'yfinance_only'])
    parser.add_argument('--test', type=str, help='Test specific ticker')
    parser.add_argument('--no-csv', action='store_true', help='不保存 CSV 备份')
    parser.add_argument('--cron', action='store_true', help='Cron 模式')
    return parser.parse_args()


def main():
    args = parse_args()

    log("=" * 50)
    log("save_prices_yfinance.py v2.1 (yfinance + SQLite, 增量模式) 开始执行")

    # 初始化 DB & 同步 watchlist
    init_db()
    config = load_config()
    sync_watchlist(config)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    # 构建 ticker 列表
    tickers = build_ticker_list(config, args.mode)

    if args.test:
        tickers = [{'symbol': args.test, 'yf_ticker': args.test}]

    if not tickers:
        log("没有需要通过 yfinance 拉取的 ticker")
        print("\n📭 没有需要通过 yfinance 拉取的 ticker")
        return

    symbols_display = [f"{t['symbol']}({t['yf_ticker']})" for t in tickers]
    log(f"共 {len(tickers)} 只 ticker: {', '.join(symbols_display)}")
    log("数据源: Yahoo Finance (yfinance)")
    log(f"请求间隔: {REQUEST_DELAY}s（防限流）")

    success = []
    failed = []
    skipped = []

    for i, t in enumerate(tickers):
        symbol = t['symbol']
        yf_ticker = t['yf_ticker']

        # ── 增量检查：查看 DB 中最新价格日期 ──
        last_date = get_latest_price_date(symbol)
        if last_date:
            from datetime import date as date_type
            today_str = datetime.now().strftime('%Y-%m-%d')
            if last_date >= today_str:
                log(f"  {symbol} 已是最新 ({last_date})，跳过")
                skipped.append(symbol)
                continue

            # 增量拉取：只拉 last_date 之后的数据
            log(f"📥 {symbol} (yfinance: {yf_ticker}) 增量更新 (从 {last_date} 起)...")
            from_date = datetime.strptime(last_date, '%Y-%m-%d') + timedelta(days=1)
            days_to_fetch = (datetime.now() - from_date).days + 2
            rows = fetch_yfinance(yf_ticker, days=max(days_to_fetch, 7))

            # 只保留 last_date 之后的行
            if rows:
                rows = [r for r in rows if r['Date'] > last_date]
        else:
            # 无历史数据，全量拉取
            log(f"📥 {symbol} (yfinance: {yf_ticker}) 全量拉取...")
            rows = fetch_yfinance(yf_ticker, days=365)

        if rows:
            try:
                # 写入 DB（主存储）
                save_to_db(symbol, rows)

                # 写入 CSV（备份）
                if not args.no_csv:
                    # 增量模式下追加到已有 CSV
                    save_csv(symbol, rows)

                latest = rows[-1]
                db_count = get_price_count(symbol)
                log(f"  {symbol} 已保存 {len(rows)} 条新数据 (DB总计 {db_count})，最新: {latest['Date']}, {latest['Close']}")
                success.append(symbol)
            except Exception as e:
                log(f"{symbol} 保存失败: {e}", "ERROR")
                failed.append(symbol)
        else:
            if last_date:
                log(f"  {symbol} 无新数据 (最新: {last_date})，跳过")
                skipped.append(symbol)
            else:
                log(f"  {symbol} 数据获取失败", "ERROR")
                failed.append(symbol)

        # 相邻请求间隔
        if i < len(tickers) - 1:
            delay = REQUEST_DELAY + random.uniform(0.5, 1.5)
            time.sleep(delay)

    log("=" * 50)
    log(f"完成: {len(success)} 只更新, {len(skipped)} 只跳过, {len(failed)} 只失败")
    if failed:
        log(f"失败: {failed}", "ERROR")

    # ── 价格更新后自动运行策略和 Market Pulse ──
    if success:
        log("=" * 50)
        log("开始自动运行策略计算和 Market Pulse 更新...")

        # 运行策略计算
        try:
            from lib.pipeline import _run_strategies_for_ticker
            from lib.db import get_watchlist

            watchlist = {t['symbol']: t for t in get_watchlist(enabled_only=True, source_type='monitored')}
            strategies_ok = 0
            strategies_fail = 0

            for symbol in success:
                # 只对 monitored 类型的 ticker 运行策略
                ticker_info = watchlist.get(symbol)
                if not ticker_info:
                    continue
                try:
                    _run_strategies_for_ticker(
                        symbol,
                        ticker_info.get('name', symbol),
                        ticker_info.get('sector', ''),
                    )
                    strategies_ok += 1
                    log(f"  {symbol} 策略计算完成")
                except Exception as e:
                    strategies_fail += 1
                    log(f"  {symbol} 策略计算失败: {e}", "WARNING")

            log(f"策略计算完成: {strategies_ok} 成功, {strategies_fail} 失败")
        except Exception as e:
            log(f"策略计算整体失败: {e}", "ERROR")

        # 运行 Market Pulse 更新
        try:
            from lib.pipeline import _update_market_pulse
            if _update_market_pulse():
                log("Market Pulse 已自动更新")
            else:
                log("Market Pulse 更新失败", "WARNING")
        except Exception as e:
            log(f"Market Pulse 更新失败: {e}", "ERROR")

    log("=" * 50)
    print(f"\n📦 yfinance 价格存档完成 | 更新 {len(success)}/{len(tickers)} | 跳过: {len(skipped)} | 失败: {failed if failed else '无'}")

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
