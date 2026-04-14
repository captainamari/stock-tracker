#!/usr/bin/env python3
"""
收盘价抓取脚本 v3.0 - Stooq 数据源
每个交易日收盘后运行，全量拉取过去一年数据

v3.0 变更：
  - 数据写入 SQLite DB（主存储）
  - CSV 文件仅作备用缓存保留
  - 使用 lib.config 加载 ticker 配置
  - 使用 lib.db 写入价格数据

数据来源: stooq.com（无需认证，无速率限制）
"""

import urllib.request
import csv
import io
import time
import random
import sys
import argparse
from datetime import datetime, timedelta
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from lib.db import init_db, upsert_prices, get_price_count, get_latest_price_date
from lib.config import load_config, parse_tickers, sync_watchlist

# 路径
DATA_DIR = PROJECT_ROOT / "data" / "prices"
LOGS_DIR = PROJECT_ROOT / "logs"
LOG_FILE = LOGS_DIR / "save_prices.log"

# stooq 请求参数
REQUEST_DELAY = 1.0   # 每次请求间隔（秒），stooq 无需大延迟
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


def fetch_stooq(ticker, days=365, retries=MAX_RETRIES):
    """
    从 stooq.com 拉取历史数据
    返回: list of dict [{Date, Open, High, Low, Close, Volume}, ...]
    """
    end = datetime.today()
    start = end - timedelta(days=days)
    d1 = start.strftime("%Y%m%d")
    d2 = end.strftime("%Y%m%d")

    # stooq 美股 ticker 加 .US 后缀
    stooq_symbol = f"{ticker}.US"
    url = f"https://stooq.com/q/d/l/?s={stooq_symbol}&d1={d1}&d2={d2}&i=d"

    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
    }

    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw = resp.read().decode('utf-8')

            # stooq 在无数据时返回 "No data" 或空 CSV
            if not raw.strip() or 'No data' in raw or len(raw.strip().split('\n')) <= 1:
                log(f"{ticker} stooq 无数据返回（可能 ticker 格式有误）", "WARNING")
                return None

            reader = csv.DictReader(io.StringIO(raw))
            rows = []
            for row in reader:
                try:
                    rows.append({
                        'Date': row['Date'],
                        'Open': f"{float(row['Open']):.4f}",
                        'High': f"{float(row['High']):.4f}",
                        'Low':  f"{float(row['Low']):.4f}",
                        'Close': f"{float(row['Close']):.4f}",
                        'Volume': str(int(float(row.get('Volume', 0) or 0))),
                    })
                except (ValueError, KeyError):
                    continue  # 跳过格式异常行

            if rows:
                # stooq 返回的数据是倒序（新→旧），排成升序
                rows.sort(key=lambda r: r['Date'])
                return rows

        except Exception as e:
            if attempt < retries - 1:
                wait = 3 + random.uniform(1, 3)
                log(f"{ticker} 第 {attempt+1} 次失败 ({e})，{wait:.1f}s 后重试...", "WARNING")
                time.sleep(wait)
            else:
                log(f"{ticker} 拉取失败（已重试 {retries} 次）: {e}", "ERROR")

    return None


def save_to_db(ticker, rows):
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
    upsert_prices(ticker, db_rows)


def save_csv(ticker, rows):
    """写回完整 CSV 作为备用缓存（按日期升序）"""
    cache_file = DATA_DIR / f"{ticker}.csv"
    rows_sorted = sorted(rows, key=lambda r: r['Date'])
    fieldnames = ['Date', 'Open', 'High', 'Low', 'Close', 'Volume']
    with open(cache_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows_sorted)


def parse_args():
    parser = argparse.ArgumentParser(description="save_prices v3.0 — Stooq 数据源")
    parser.add_argument("--no-csv", action="store_true", help="不保存 CSV 备份")
    parser.add_argument("--cron", action="store_true", help="Cron 模式")
    return parser.parse_args()


def main():
    args = parse_args()

    log("=" * 50)
    log("save_prices.py v3.0 (stooq + SQLite) 开始执行")

    # 初始化 DB & 同步 watchlist
    init_db()
    config = load_config()
    sync_watchlist(config)

    # 获取 monitored 组的 ticker 列表（stooq 源）
    tickers_info = parse_tickers(config)
    monitored = [t for t in tickers_info if t.source_type == 'monitored' and t.enabled]

    # 确保 benchmark 也在列表中
    benchmark = config.get('benchmark', 'SPY')
    symbols = [t.symbol for t in monitored]
    if benchmark not in symbols:
        symbols.append(benchmark)
    else:
        symbols = list(symbols)  # ensure it's a list

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    log(f"共 {len(symbols)} 只股票: {', '.join(symbols)}")
    log("数据源: stooq.com（全量拉取过去 365 天）")

    success = []
    failed = []

    for i, ticker in enumerate(symbols):
        log(f"📥 {ticker}...")
        rows = fetch_stooq(ticker, days=365)

        if rows:
            try:
                # 写入 DB（主存储）
                # save_to_db(ticker, rows)

                # 写入 CSV（备份）
                if not args.no_csv:
                    save_csv(ticker, rows)

                latest = rows[-1]
                db_count = get_price_count(ticker)
                log(f"  {ticker} 已保存 {len(rows)} 条 (DB总计 {db_count})，最新: {latest['Date']}, {latest['Close']}")
                success.append(ticker)
            except Exception as e:
                log(f"{ticker} 保存失败: {e}", "ERROR")
                failed.append(ticker)
        else:
            log(f"  {ticker} 数据获取失败", "ERROR")
            failed.append(ticker)

        # 相邻请求间隔
        if i < len(symbols) - 1:
            time.sleep(REQUEST_DELAY)

    log("=" * 50)
    log(f"完成: {len(success)} 只成功 {success}")
    if failed:
        log(f"失败: {failed}", "ERROR")
    log("=" * 50)

    print(f"\n📦 价格存档完成 | 成功 {len(success)}/{len(symbols)} | 失败: {failed if failed else '无'}")

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
