"""
Stock Tracker — 单 Ticker 管道
Web 添加 ticker 时使用：验证合法性 → 拉取价格 → 跑全部策略

用法:
    from lib.pipeline import validate_ticker, run_single_ticker_pipeline

    # 1. 先验证
    result = validate_ticker("AAPL")
    if not result['valid']:
        print(result['error'])

    # 2. 再跑管道
    pipeline_result = run_single_ticker_pipeline("AAPL", "Apple Inc.", "Technology")
"""

import re
import math
import logging
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

# 合法的美股 ticker 格式: 1-5 个大写字母，可带 .A/.B 后缀
_TICKER_PATTERN = re.compile(r'^[A-Z]{1,5}(\.[A-Z]{1,2})?$')


# ============================================================
# Ticker 验证（三层防线）
# ============================================================
def validate_ticker(symbol: str) -> dict:
    """
    验证 ticker 是否合法、数据源是否可用。

    三层验证:
      1. 格式校验 (本地, 0ms)
      2. yf.Ticker(s).info 元数据检查 (~1s)
      3. 试拉 5 天历史数据确认数据可用 (~1s)

    返回 dict:
      valid: bool
      symbol: str (标准化)
      name: str | None
      sector: str | None
      exchange: str | None
      currency: str | None
      market_price: float | None
      error: str | None
    """
    result = {
        'valid': False,
        'symbol': '',
        'name': None,
        'sector': None,
        'exchange': None,
        'currency': None,
        'market_price': None,
        'error': None,
    }

    # ── 第1层: 格式校验 ──
    symbol = symbol.strip().upper()
    result['symbol'] = symbol

    if not symbol:
        result['error'] = '请输入 ticker 代码'
        return result

    if not _TICKER_PATTERN.match(symbol):
        result['error'] = (
            f'"{symbol}" 格式无效。'
            '美股 ticker 由 1-5 个字母组成（如 AAPL, NVDA, BRK.B）'
        )
        return result

    # ── 第2层: yfinance info 元数据检查 ──
    try:
        import yfinance as yf
    except ImportError:
        result['error'] = 'yfinance 未安装'
        return result

    try:
        ticker_obj = yf.Ticker(symbol)
        info = ticker_obj.info

        # yfinance 对无效 ticker 的行为不一致:
        #   - 有时 info 为空 dict {}
        #   - 有时 info 只有 {'trailingPegRatio': None} 等无意义字段
        #   - 合法 ticker 一定有 shortName 或 longName
        name = info.get('shortName') or info.get('longName')
        if not name:
            result['error'] = (
                f'找不到 "{symbol}"。请检查拼写是否正确，'
                '或该 ticker 是否已退市。'
            )
            return result

        result['name'] = name
        result['sector'] = info.get('sector', '') or info.get('industry', '')
        result['exchange'] = info.get('exchange', '')
        result['currency'] = info.get('currency', 'USD')
        result['market_price'] = info.get('regularMarketPrice')

    except Exception as e:
        logger.warning(f"validate_ticker info 请求失败 [{symbol}]: {e}")
        result['error'] = f'无法获取 "{symbol}" 的信息: {str(e)}'
        return result

    # ── 第3层: 试拉少量历史数据 ──
    try:
        test_df = ticker_obj.history(period='5d')
        if test_df is None or test_df.empty:
            result['error'] = (
                f'"{symbol}" ({name}) 存在但暂时无法获取交易数据。'
                '可能是极新的 IPO 或数据源暂时不可用。'
            )
            return result

        # 检查 Close 列是否有有效数据
        valid_closes = [c for c in test_df['Close'] if not math.isnan(c)]
        if not valid_closes:
            result['error'] = f'"{symbol}" 近期无有效交易数据'
            return result

    except Exception as e:
        logger.warning(f"validate_ticker 历史数据检查失败 [{symbol}]: {e}")
        result['error'] = f'"{symbol}" 数据拉取测试失败: {str(e)}'
        return result

    # ── 全部通过 ──
    result['valid'] = True
    return result


# ============================================================
# 单 Ticker 管道
# ============================================================
def run_single_ticker_pipeline(symbol: str, name: str, sector: str) -> dict:
    """
    对单只 ticker 执行完整的策略管道:
      1. 拉取历史价格 (yfinance, 365 天)
      2. 写入 DB
      3. 运行 Stage 2 分析
      4. 运行 VCP 分析 (依赖 Stage 2 状态)
      5. 运行 Bottom Fisher 分析

    返回:
        {
            'success': True/False,
            'symbol': str,
            'prices_count': int,
            'stage2': dict | None,
            'vcp': dict | None,
            'bottom_fisher': dict | None,
            'error': str | None,
        }
    """
    import sys
    PROJECT_ROOT = Path(__file__).parent.parent
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    from lib.db import (
        init_db, upsert_prices, get_prices_as_dataframe,
        save_strategy_result, upsert_strategy_state,
        get_strategy_state,
    )
    from lib.models import TickerInfo

    pipeline_result = {
        'success': False,
        'symbol': symbol,
        'prices_count': 0,
        'stage2': None,
        'vcp': None,
        'bottom_fisher': None,
        'error': None,
    }

    date_str = datetime.now().strftime('%Y-%m-%d')

    # ── Step 1: 拉取价格数据 ──
    try:
        import yfinance as yf

        logger.info(f"[Pipeline] {symbol}: 拉取历史价格...")
        ticker_obj = yf.Ticker(symbol)
        end = datetime.today()
        start = end - timedelta(days=365)

        df = ticker_obj.history(
            start=start.strftime('%Y-%m-%d'),
            end=end.strftime('%Y-%m-%d'),
            auto_adjust=True,
        )

        if df is None or df.empty:
            # 尝试 auto_adjust=False
            df = ticker_obj.history(
                start=start.strftime('%Y-%m-%d'),
                end=end.strftime('%Y-%m-%d'),
                auto_adjust=False,
            )

        if df is None or df.empty:
            pipeline_result['error'] = f'无法获取 {symbol} 的历史价格数据'
            return pipeline_result

        # 转换为 DB 格式
        db_rows = []
        for idx, row in df.iterrows():
            try:
                o = float(row['Open'])
                h = float(row['High'])
                l = float(row['Low'])
                c = float(row['Close'])
                if math.isnan(o) or math.isnan(h) or math.isnan(l) or math.isnan(c):
                    continue
                db_rows.append({
                    'date': idx.strftime('%Y-%m-%d'),
                    'open': o,
                    'high': h,
                    'low': l,
                    'close': c,
                    'volume': int(float(row.get('Volume', 0) or 0)),
                })
            except (ValueError, KeyError):
                continue

        if not db_rows:
            pipeline_result['error'] = f'{symbol} 历史数据全部无效'
            return pipeline_result

        upsert_prices(symbol, db_rows)
        pipeline_result['prices_count'] = len(db_rows)
        logger.info(f"[Pipeline] {symbol}: 已保存 {len(db_rows)} 条价格数据")

    except Exception as e:
        logger.error(f"[Pipeline] {symbol}: 价格拉取失败: {e}")
        pipeline_result['error'] = f'价格数据拉取失败: {str(e)}'
        return pipeline_result

    # ── Step 2: 运行 Stage 2 ──
    try:
        from scripts.stage2_monitor import check_stage2_conditions

        ticker_info = TickerInfo(symbol=symbol, name=name, sector=sector)
        s2_result = check_stage2_conditions(ticker_info)

        if s2_result:
            # 写入策略结果
            save_strategy_result(
                symbol=symbol,
                date_str=date_str,
                strategy='stage2',
                is_signal=s2_result['is_stage2'],
                score=s2_result['trend_power'],
                passed=s2_result['passed'],
                total=s2_result['total'],
                conditions=s2_result['conditions'],
                condition_details=s2_result.get('condition_details', {}),
                metrics={
                    'name': name, 'sector': sector,
                    'price': s2_result['price'],
                    'sma50': s2_result['sma50'],
                    'sma150': s2_result['sma150'],
                    'sma200': s2_result['sma200'],
                    'week52_high': s2_result['week52_high'],
                    'week52_low': s2_result['week52_low'],
                    'pct_from_high': s2_result['pct_from_high'],
                    'pct_from_low': s2_result['pct_from_low'],
                    'pct_above_sma200': s2_result['pct_above_sma200'],
                    'pct_above_sma50': s2_result['pct_above_sma50'],
                    'trend_power': s2_result['trend_power'],
                    'vol_signal': s2_result.get('vol_signal', ''),
                    'stock_return_6m': s2_result.get('stock_return_6m'),
                    'spy_return_6m': s2_result.get('spy_return_6m'),
                    'chg_5d': s2_result.get('chg_5d'),
                    'chg_20d': s2_result.get('chg_20d'),
                    'sma50_slope': s2_result.get('sma50_slope'),
                },
                summary=f"{'S2' if s2_result['is_stage2'] else '--'} {symbol} "
                        f"{s2_result['passed']}/{s2_result['total']} "
                        f"TP:{s2_result['trend_power']}",
            )

            # 写入策略状态
            upsert_strategy_state(
                symbol=symbol,
                strategy='stage2',
                is_active=s2_result['is_stage2'],
                entry_date=date_str if s2_result['is_stage2'] else None,
                entry_price=s2_result['price'] if s2_result['is_stage2'] else None,
            )

            pipeline_result['stage2'] = {
                'is_signal': s2_result['is_stage2'],
                'score': s2_result['trend_power'],
                'passed': s2_result['passed'],
                'total': s2_result['total'],
            }
            logger.info(f"[Pipeline] {symbol}: Stage2 {'✅' if s2_result['is_stage2'] else '❌'} "
                        f"({s2_result['passed']}/{s2_result['total']}, TP:{s2_result['trend_power']})")

    except Exception as e:
        logger.warning(f"[Pipeline] {symbol}: Stage2 分析失败: {e}")

    # ── Step 3: 运行 VCP (依赖 Stage 2 状态) ──
    try:
        from scripts.vcp_scanner import analyze_vcp

        data = get_prices_as_dataframe(symbol, min_rows=200)
        s2_state = get_strategy_state(symbol, 'stage2')

        if data is not None and s2_state and s2_state.get('is_active'):
            t_info = {'name': name, 'sector': sector, 'symbol': symbol}
            vcp_result = analyze_vcp(symbol, t_info, data, s2_state)

            if vcp_result:
                save_strategy_result(
                    symbol=symbol,
                    date_str=date_str,
                    strategy='vcp',
                    is_signal=vcp_result['is_vcp'],
                    score=vcp_result['vcp_score'],
                    passed=vcp_result['passed'],
                    total=vcp_result['total'],
                    conditions=vcp_result['conditions'],
                    condition_details=vcp_result.get('condition_details', {}),
                    metrics={
                        'name': name, 'sector': sector,
                        'price': vcp_result['price'],
                        'vcp_score': vcp_result['vcp_score'],
                        'days_in_stage2': vcp_result.get('days_in_stage2', 0),
                        'entry_price': vcp_result.get('entry_price'),
                        'week52_high': vcp_result['week52_high'],
                        'week52_low': vcp_result['week52_low'],
                        'sma50': vcp_result['sma50'],
                        'sma150': vcp_result.get('sma150'),
                        'sma10': vcp_result['sma10'],
                        'chg_5d': vcp_result.get('chg_5d'),
                        'chg_20d': vcp_result.get('chg_20d'),
                        **vcp_result.get('metrics', {}),
                    },
                    summary=f"{'VCP' if vcp_result['is_vcp'] else '--'} {symbol} "
                            f"{vcp_result['passed']}/{vcp_result['total']} "
                            f"Score:{vcp_result['vcp_score']}",
                )

                upsert_strategy_state(
                    symbol=symbol,
                    strategy='vcp',
                    is_active=vcp_result['is_vcp'],
                    entry_date=date_str if vcp_result['is_vcp'] else None,
                    entry_price=vcp_result['price'] if vcp_result['is_vcp'] else None,
                    extra={'vcp_score': vcp_result['vcp_score']},
                )

                pipeline_result['vcp'] = {
                    'is_signal': vcp_result['is_vcp'],
                    'score': vcp_result['vcp_score'],
                    'passed': vcp_result['passed'],
                    'total': vcp_result['total'],
                }
                logger.info(f"[Pipeline] {symbol}: VCP {'✅' if vcp_result['is_vcp'] else '❌'} "
                            f"(Score:{vcp_result['vcp_score']})")
        else:
            logger.info(f"[Pipeline] {symbol}: VCP 跳过 (非 Stage2 或数据不足)")

    except Exception as e:
        logger.warning(f"[Pipeline] {symbol}: VCP 分析失败: {e}")

    # ── Step 4: 运行 Bottom Fisher ──
    try:
        from scripts.bottom_fisher import analyze_bottom
        from lib.db import get_strategy_states

        data = get_prices_as_dataframe(symbol, min_rows=200)

        if data is not None:
            # 获取 stage2 states 用于质地判断
            stage2_states_list = get_strategy_states('stage2')
            stage2_states = {s['symbol']: s for s in stage2_states_list}

            ticker_info = TickerInfo(symbol=symbol, name=name, sector=sector)
            bf_result = analyze_bottom(symbol, ticker_info, data, stage2_states)

            if bf_result:
                save_strategy_result(
                    symbol=symbol,
                    date_str=date_str,
                    strategy='bottom_fisher',
                    is_signal=bf_result['is_bottom_signal'],
                    score=bf_result['bf_score'],
                    passed=bf_result['passed'],
                    total=bf_result['total'],
                    conditions=bf_result['conditions'],
                    condition_details=bf_result.get('condition_details', {}),
                    metrics={
                        'name': name, 'sector': sector,
                        'price': bf_result['price'],
                        'bf_score': bf_result['bf_score'],
                        'bonuses': bf_result.get('bonuses', {}),
                        'week52_high': bf_result['week52_high'],
                        'week52_low': bf_result['week52_low'],
                        'sma50': bf_result.get('sma50'),
                        'sma200': bf_result.get('sma200'),
                        'sma10': bf_result.get('sma10'),
                        'chg_5d': bf_result.get('chg_5d'),
                        'chg_20d': bf_result.get('chg_20d'),
                    },
                    summary=f"{'BF' if bf_result['is_bottom_signal'] else '--'} {symbol} "
                            f"{bf_result['passed']}/{bf_result['total']} "
                            f"Score:{bf_result['bf_score']}",
                )

                upsert_strategy_state(
                    symbol=symbol,
                    strategy='bottom_fisher',
                    is_active=bf_result['is_bottom_signal'],
                    entry_date=date_str if bf_result['is_bottom_signal'] else None,
                    entry_price=bf_result['price'] if bf_result['is_bottom_signal'] else None,
                    extra={'bf_score': bf_result['bf_score']},
                )

                pipeline_result['bottom_fisher'] = {
                    'is_signal': bf_result['is_bottom_signal'],
                    'score': bf_result['bf_score'],
                    'passed': bf_result['passed'],
                    'total': bf_result['total'],
                }
                logger.info(f"[Pipeline] {symbol}: BottomFisher {'✅' if bf_result['is_bottom_signal'] else '❌'} "
                            f"(Score:{bf_result['bf_score']})")

    except Exception as e:
        logger.warning(f"[Pipeline] {symbol}: Bottom Fisher 分析失败: {e}")

    pipeline_result['success'] = True
    logger.info(f"[Pipeline] {symbol}: 管道执行完成")
    return pipeline_result
