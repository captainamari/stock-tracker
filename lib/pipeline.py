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

    # 3. 全量刷新价格（Web 按钮触发）
    for progress in refresh_all_prices():
        print(progress)  # 逐 ticker 进度
"""

import re
import math
import time
import logging
from datetime import datetime, timedelta
from pathlib import Path

try:
    from lib.encoding_fix import ensure_utf8_output
    ensure_utf8_output()
except ImportError:
    pass  # encoding fix already applied via lib.db import

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
        'buying_checklist': None,
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

    # ── Step 5: 运行 Buying Checklist ──
    try:
        from scripts.buying_checklist import analyze_buying_checklist

        data = get_prices_as_dataframe(symbol, min_rows=200)

        if data is not None:
            stage2_states_list = get_strategy_states('stage2')
            stage2_states = {s['symbol']: s for s in stage2_states_list}
            bf_states_list = get_strategy_states('bottom_fisher')
            bf_states = {s['symbol']: s for s in bf_states_list}

            ticker_info = TickerInfo(symbol=symbol, name=name, sector=sector)
            bc_result = analyze_buying_checklist(symbol, ticker_info, data, stage2_states, bf_states)

            if bc_result:
                save_strategy_result(
                    symbol=symbol,
                    date_str=date_str,
                    strategy='buying_checklist',
                    is_signal=bc_result['is_bc_signal'],
                    score=bc_result['bc_score'],
                    passed=bc_result['passed'],
                    total=bc_result['total'],
                    conditions=bc_result['conditions'],
                    condition_details=bc_result.get('condition_details', {}),
                    metrics={
                        'name': name, 'sector': sector,
                        'price': bc_result['price'],
                        'bc_score': bc_result['bc_score'],
                        'weekly_impulse': bc_result['weekly_impulse'],
                        'weekly_trend': bc_result['weekly_trend'],
                        'impulse_streak': bc_result['impulse_streak'],
                        'week52_high': bc_result['week52_high'],
                        'week52_low': bc_result['week52_low'],
                        'sma50': bc_result.get('sma50'),
                        'sma200': bc_result.get('sma200'),
                        'sma10': bc_result.get('sma10'),
                        'chg_5d': bc_result.get('chg_5d'),
                        'chg_20d': bc_result.get('chg_20d'),
                    },
                    summary=f"{'BC' if bc_result['is_bc_signal'] else '--'} {symbol} "
                            f"{bc_result['passed']}/{bc_result['total']} "
                            f"Score:{bc_result['bc_score']}",
                )

                upsert_strategy_state(
                    symbol=symbol,
                    strategy='buying_checklist',
                    is_active=bc_result['is_bc_signal'],
                    entry_date=date_str if bc_result['is_bc_signal'] else None,
                    entry_price=bc_result['price'] if bc_result['is_bc_signal'] else None,
                    extra={'bc_score': bc_result['bc_score']},
                )

                pipeline_result['buying_checklist'] = {
                    'is_signal': bc_result['is_bc_signal'],
                    'score': bc_result['bc_score'],
                    'passed': bc_result['passed'],
                    'total': bc_result['total'],
                }
                logger.info(f"[Pipeline] {symbol}: BuyingChecklist {'✅' if bc_result['is_bc_signal'] else '❌'} "
                            f"(Score:{bc_result['bc_score']})")

    except Exception as e:
        logger.warning(f"[Pipeline] {symbol}: Buying Checklist 分析失败: {e}")

    pipeline_result['success'] = True
    logger.info(f"[Pipeline] {symbol}: 管道执行完成")
    return pipeline_result


# ============================================================
# 全量价格刷新 — Web 按钮触发
# ============================================================
def _fetch_incremental_prices(symbol: str, last_date: str) -> list:
    """
    增量拉取价格：从 DB 中最后一条记录到今天。
    仅拉最近 30 天以避免浪费 API 配额。
    返回 list[dict] 格式：[{date, open, high, low, close, volume}, ...]
    """
    import yfinance as yf

    # 从 last_date 的次日开始拉取
    start = datetime.strptime(last_date, '%Y-%m-%d') + timedelta(days=1)
    end = datetime.today() + timedelta(days=1)  # 包含今天

    if start >= end:
        return []

    ticker_obj = yf.Ticker(symbol)
    df = ticker_obj.history(
        start=start.strftime('%Y-%m-%d'),
        end=end.strftime('%Y-%m-%d'),
        auto_adjust=True,
    )

    if df is None or df.empty:
        # fallback
        df = ticker_obj.history(
            start=start.strftime('%Y-%m-%d'),
            end=end.strftime('%Y-%m-%d'),
            auto_adjust=False,
        )

    if df is None or df.empty:
        return []

    rows = []
    for idx, row in df.iterrows():
        try:
            o = float(row['Open'])
            h = float(row['High'])
            l = float(row['Low'])
            c = float(row['Close'])
            if math.isnan(o) or math.isnan(h) or math.isnan(l) or math.isnan(c):
                continue
            rows.append({
                'date': idx.strftime('%Y-%m-%d'),
                'open': o,
                'high': h,
                'low': l,
                'close': c,
                'volume': int(float(row.get('Volume', 0) or 0)),
            })
        except (ValueError, KeyError):
            continue

    return rows


def _update_market_pulse() -> bool:
    """
    运行 Market Pulse 分析并将结果写入 DB。
    在 refresh_all_prices 完成后自动调用，确保 market_pulse 表
    的日期与策略结果日期一致。

    返回: True 如果成功更新，False 如果失败或跳过。
    """
    import sys
    PROJECT_ROOT = Path(__file__).parent.parent
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    from lib.db import (
        get_prices_as_dataframe, save_market_pulse,
        get_latest_market_pulse, get_strategy_states,
    )
    from lib.config import get_monitored_tickers

    try:
        from scripts.market_pulse import (
            analyze_index, analyze_vix, analyze_breadth,
            calculate_composite_score, determine_regime,
        )
    except ImportError as e:
        logger.warning(f"[MarketPulse] 无法导入 market_pulse 模块: {e}")
        return False

    try:
        # 加载 Stage 2 状态
        stage2_states_list = get_strategy_states('stage2')
        stage2_states = {s['symbol']: s for s in stage2_states_list}

        # 加载指数数据
        spy_data = get_prices_as_dataframe('SPY', min_rows=50)
        qqq_data = get_prices_as_dataframe('QQQ', min_rows=20)
        iwm_data = get_prices_as_dataframe('IWM', min_rows=20)
        vix_data = get_prices_as_dataframe('VIX', min_rows=10)

        # 分析
        spy_result = analyze_index('SPY', spy_data)
        qqq_result = analyze_index('QQQ', qqq_data)
        iwm_result = analyze_index('IWM', iwm_data)
        vix_result = analyze_vix(vix_data)
        breadth_result = analyze_breadth(stage2_states)

        # 综合评分
        composite, scores = calculate_composite_score(
            spy_result, qqq_result, iwm_result, vix_result, breadth_result
        )
        regime_info = determine_regime(composite, spy_result, vix_result)
        regime = regime_info[0]

        # 写入 DB
        date_str = datetime.now().strftime('%Y-%m-%d')
        save_market_pulse(
            date_str=date_str,
            regime=regime,
            composite_score=composite,
            component_scores=scores,
            spy_price=spy_result['price'] if spy_result else None,
            vix_value=vix_result['value'] if vix_result else None,
            index_data={
                'SPY': spy_result or {},
                'QQQ': qqq_result or {},
                'IWM': iwm_result or {},
                'VIX': vix_result or {},
            },
            breadth_data=breadth_result or {},
        )
        logger.info(f"[MarketPulse] 已更新: {date_str} {regime} ({composite}/100)")
        return True

    except Exception as e:
        logger.error(f"[MarketPulse] 更新失败: {e}")
        return False


def _run_strategies_for_ticker(symbol: str, name: str, sector: str) -> dict:
    """
    对单只 ticker 运行全部策略（Stage2 + VCP + Bottom Fisher）。
    与 run_single_ticker_pipeline 的 Step 2~4 逻辑相同，但不拉取价格。
    """
    import sys
    PROJECT_ROOT = Path(__file__).parent.parent
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    from lib.db import (
        get_prices_as_dataframe,
        save_strategy_result, upsert_strategy_state,
        get_strategy_state, get_strategy_states,
    )
    from lib.models import TickerInfo

    result = {'stage2': None, 'vcp': None, 'bottom_fisher': None, 'buying_checklist': None}
    date_str = datetime.now().strftime('%Y-%m-%d')

    # Stage 2
    try:
        from scripts.stage2_monitor import check_stage2_conditions
        ticker_info = TickerInfo(symbol=symbol, name=name, sector=sector)
        s2_result = check_stage2_conditions(ticker_info)
        if s2_result:
            save_strategy_result(
                symbol=symbol, date_str=date_str, strategy='stage2',
                is_signal=s2_result['is_stage2'], score=s2_result['trend_power'],
                passed=s2_result['passed'], total=s2_result['total'],
                conditions=s2_result['conditions'],
                condition_details=s2_result.get('condition_details', {}),
                metrics={
                    'name': name, 'sector': sector,
                    'price': s2_result['price'],
                    'sma50': s2_result['sma50'], 'sma150': s2_result['sma150'],
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
            upsert_strategy_state(
                symbol=symbol, strategy='stage2',
                is_active=s2_result['is_stage2'],
                entry_date=date_str if s2_result['is_stage2'] else None,
                entry_price=s2_result['price'] if s2_result['is_stage2'] else None,
            )
            result['stage2'] = {
                'is_signal': s2_result['is_stage2'],
                'score': s2_result['trend_power'],
            }
    except Exception as e:
        logger.warning(f"[Refresh] {symbol}: Stage2 分析失败: {e}")

    # VCP
    try:
        from scripts.vcp_scanner import analyze_vcp
        data = get_prices_as_dataframe(symbol, min_rows=200)
        s2_state = get_strategy_state(symbol, 'stage2')
        if data is not None and s2_state and s2_state.get('is_active'):
            t_info = {'name': name, 'sector': sector, 'symbol': symbol}
            vcp_result = analyze_vcp(symbol, t_info, data, s2_state)
            if vcp_result:
                save_strategy_result(
                    symbol=symbol, date_str=date_str, strategy='vcp',
                    is_signal=vcp_result['is_vcp'], score=vcp_result['vcp_score'],
                    passed=vcp_result['passed'], total=vcp_result['total'],
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
                    symbol=symbol, strategy='vcp',
                    is_active=vcp_result['is_vcp'],
                    entry_date=date_str if vcp_result['is_vcp'] else None,
                    entry_price=vcp_result['price'] if vcp_result['is_vcp'] else None,
                    extra={'vcp_score': vcp_result['vcp_score']},
                )
                result['vcp'] = {
                    'is_signal': vcp_result['is_vcp'],
                    'score': vcp_result['vcp_score'],
                }
    except Exception as e:
        logger.warning(f"[Refresh] {symbol}: VCP 分析失败: {e}")

    # Bottom Fisher
    try:
        from scripts.bottom_fisher import analyze_bottom
        data = get_prices_as_dataframe(symbol, min_rows=200)
        if data is not None:
            stage2_states_list = get_strategy_states('stage2')
            stage2_states = {s['symbol']: s for s in stage2_states_list}
            ticker_info = TickerInfo(symbol=symbol, name=name, sector=sector)
            bf_result = analyze_bottom(symbol, ticker_info, data, stage2_states)
            if bf_result:
                save_strategy_result(
                    symbol=symbol, date_str=date_str, strategy='bottom_fisher',
                    is_signal=bf_result['is_bottom_signal'], score=bf_result['bf_score'],
                    passed=bf_result['passed'], total=bf_result['total'],
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
                    symbol=symbol, strategy='bottom_fisher',
                    is_active=bf_result['is_bottom_signal'],
                    entry_date=date_str if bf_result['is_bottom_signal'] else None,
                    entry_price=bf_result['price'] if bf_result['is_bottom_signal'] else None,
                    extra={'bf_score': bf_result['bf_score']},
                )
                result['bottom_fisher'] = {
                    'is_signal': bf_result['is_bottom_signal'],
                    'score': bf_result['bf_score'],
                }
    except Exception as e:
        logger.warning(f"[Refresh] {symbol}: Bottom Fisher 分析失败: {e}")

    # Buying Checklist
    try:
        from scripts.buying_checklist import analyze_buying_checklist
        data = get_prices_as_dataframe(symbol, min_rows=200)
        if data is not None:
            stage2_states_list = get_strategy_states('stage2')
            stage2_states = {s['symbol']: s for s in stage2_states_list}
            bf_states_list = get_strategy_states('bottom_fisher')
            bf_states = {s['symbol']: s for s in bf_states_list}
            ticker_info = TickerInfo(symbol=symbol, name=name, sector=sector)
            bc_result = analyze_buying_checklist(symbol, ticker_info, data, stage2_states, bf_states)
            if bc_result:
                save_strategy_result(
                    symbol=symbol, date_str=date_str, strategy='buying_checklist',
                    is_signal=bc_result['is_bc_signal'], score=bc_result['bc_score'],
                    passed=bc_result['passed'], total=bc_result['total'],
                    conditions=bc_result['conditions'],
                    condition_details=bc_result.get('condition_details', {}),
                    metrics={
                        'name': name, 'sector': sector,
                        'price': bc_result['price'],
                        'bc_score': bc_result['bc_score'],
                        'weekly_impulse': bc_result['weekly_impulse'],
                        'weekly_trend': bc_result['weekly_trend'],
                        'impulse_streak': bc_result['impulse_streak'],
                        'week52_high': bc_result['week52_high'],
                        'week52_low': bc_result['week52_low'],
                        'sma50': bc_result.get('sma50'),
                        'sma200': bc_result.get('sma200'),
                        'sma10': bc_result.get('sma10'),
                        'chg_5d': bc_result.get('chg_5d'),
                        'chg_20d': bc_result.get('chg_20d'),
                    },
                    summary=f"{'BC' if bc_result['is_bc_signal'] else '--'} {symbol} "
                            f"{bc_result['passed']}/{bc_result['total']} "
                            f"Score:{bc_result['bc_score']}",
                )
                upsert_strategy_state(
                    symbol=symbol, strategy='buying_checklist',
                    is_active=bc_result['is_bc_signal'],
                    entry_date=date_str if bc_result['is_bc_signal'] else None,
                    entry_price=bc_result['price'] if bc_result['is_bc_signal'] else None,
                    extra={'bc_score': bc_result['bc_score']},
                )
                result['buying_checklist'] = {
                    'is_signal': bc_result['is_bc_signal'],
                    'score': bc_result['bc_score'],
                }
    except Exception as e:
        logger.warning(f"[Refresh] {symbol}: Buying Checklist 分析失败: {e}")

    return result


def refresh_all_prices():
    """
    全量刷新所有 enabled 个股的价格并条件性重算策略。
    这是一个 **生成器**，逐 ticker 产出进度 dict。

    使用方式:
        results = []
        for progress in refresh_all_prices():
            results.append(progress)
            # progress 结构见下

    产出的 dict:
        {
            'type': 'progress' | 'complete',
            'symbol': str,
            'current': int,       # 当前序号 (1-based)
            'total': int,         # 总数
            'status': 'updated' | 'skipped' | 'error',
            'new_rows': int,      # 新增价格行数
            'strategies_recalculated': bool,
            'error': str | None,
        }

    最后一条 type='complete' 汇总:
        {
            'type': 'complete',
            'total': int,
            'updated': int,
            'skipped': int,
            'errors': int,
            'strategies_recalculated': int,
        }
    """
    from lib.db import (
        get_watchlist, get_latest_price_date, upsert_prices,
    )

    tickers = get_watchlist(enabled_only=True, source_type='monitored')
    total = len(tickers)

    if total == 0:
        yield {
            'type': 'complete',
            'total': 0, 'updated': 0, 'skipped': 0,
            'errors': 0, 'strategies_recalculated': 0,
        }
        return

    logger.info(f"[Refresh] 开始全量价格刷新，共 {total} 只 ticker")

    updated = 0
    skipped = 0
    errors = 0
    recalculated = 0

    for i, t in enumerate(tickers, 1):
        symbol = t['symbol']
        name = t.get('name', symbol)
        sector = t.get('sector', '')

        progress = {
            'type': 'progress',
            'symbol': symbol,
            'name': name,
            'current': i,
            'total': total,
            'status': 'skipped',
            'new_rows': 0,
            'strategies_recalculated': False,
            'error': None,
        }

        try:
            last_date = get_latest_price_date(symbol)

            if not last_date:
                # 无历史数据，拉全量 365 天
                new_rows = _fetch_full_prices(symbol)
            else:
                new_rows = _fetch_incremental_prices(symbol, last_date)

            if new_rows:
                upsert_prices(symbol, new_rows)
                progress['new_rows'] = len(new_rows)
                progress['status'] = 'updated'
                updated += 1
                logger.info(f"[Refresh] {symbol}: +{len(new_rows)} 条新价格")

                # 价格有更新 → 重算策略
                try:
                    _run_strategies_for_ticker(symbol, name, sector)
                    progress['strategies_recalculated'] = True
                    recalculated += 1
                except Exception as e:
                    logger.warning(f"[Refresh] {symbol}: 策略重算失败: {e}")
            else:
                progress['status'] = 'skipped'
                skipped += 1
                logger.info(f"[Refresh] {symbol}: 价格已是最新，跳过")

        except Exception as e:
            progress['status'] = 'error'
            progress['error'] = str(e)
            errors += 1
            logger.error(f"[Refresh] {symbol}: 刷新失败: {e}")

        yield progress

        # 请求间隔 — 避免 yfinance 限流
        if i < total:
            time.sleep(1.5)

    logger.info(f"[Refresh] 全量刷新完成: 更新 {updated} / 跳过 {skipped} / 失败 {errors} / 重算策略 {recalculated}")

    # ── 刷新完成后自动更新 Market Pulse ──
    # 确保页面底部的 latest_date 与策略结果日期一致
    pulse_updated = False
    try:
        pulse_updated = _update_market_pulse()
        if pulse_updated:
            logger.info("[Refresh] Market Pulse 已自动更新")
    except Exception as e:
        logger.warning(f"[Refresh] Market Pulse 自动更新失败: {e}")

    yield {
        'type': 'complete',
        'total': total,
        'updated': updated,
        'skipped': skipped,
        'errors': errors,
        'strategies_recalculated': recalculated,
        'pulse_updated': pulse_updated,
    }


def _fetch_full_prices(symbol: str) -> list:
    """
    全量拉取 365 天价格数据（无历史记录时使用）。
    返回格式同 _fetch_incremental_prices。
    """
    import yfinance as yf

    end = datetime.today() + timedelta(days=1)
    start = end - timedelta(days=365)

    ticker_obj = yf.Ticker(symbol)
    df = ticker_obj.history(
        start=start.strftime('%Y-%m-%d'),
        end=end.strftime('%Y-%m-%d'),
        auto_adjust=True,
    )

    if df is None or df.empty:
        df = ticker_obj.history(
            start=start.strftime('%Y-%m-%d'),
            end=end.strftime('%Y-%m-%d'),
            auto_adjust=False,
        )

    if df is None or df.empty:
        return []

    rows = []
    for idx, row in df.iterrows():
        try:
            o = float(row['Open'])
            h = float(row['High'])
            l = float(row['Low'])
            c = float(row['Close'])
            if math.isnan(o) or math.isnan(h) or math.isnan(l) or math.isnan(c):
                continue
            rows.append({
                'date': idx.strftime('%Y-%m-%d'),
                'open': o,
                'high': h,
                'low': l,
                'close': c,
                'volume': int(float(row.get('Volume', 0) or 0)),
            })
        except (ValueError, KeyError):
            continue

    return rows
