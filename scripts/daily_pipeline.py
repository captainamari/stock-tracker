#!/usr/bin/env python3
"""
Stock Tracker — Daily Pipeline
================================
Three-phase pipeline for daily data update and Telegram notification.

Phase 1: DATA INGESTION  — fetch prices, sync watchlist
Phase 2: STRATEGY COMPUTE — run all strategies, persist results to DB
Phase 3: NOTIFICATION     — read from DB, render templates, push Telegram

Key design principles:
  - All notification data is read from DB (not memory), ensuring robustness
  - Idempotent: re-running skips already-completed steps
  - Each phase is independently recoverable
  - Trading day detection (skip weekends)

Usage:
    python scripts/daily_pipeline.py                # Full pipeline
    python scripts/daily_pipeline.py --notify-only  # Only push (data already in DB)
    python scripts/daily_pipeline.py --no-notify    # Only update data, skip push
    python scripts/daily_pipeline.py --dry-run      # Render messages but don't send
    python scripts/daily_pipeline.py --force        # Force re-run all steps
    python scripts/daily_pipeline.py --test-bot     # Test Telegram bot connectivity
"""

import sys
import os
import time
import argparse
import logging
import subprocess
from datetime import datetime
from pathlib import Path

# Ensure project root on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from lib.db import (
    init_db, get_db,
    get_market_pulse, get_strategy_results, get_signal_changes,
    get_strategy_states, get_watchlist,
    record_pipeline_run, get_pipeline_runs, is_pipeline_step_completed,
    record_notification, is_notification_sent,
)
from lib.report import render_template
from lib.notifier import (
    TelegramNotifier, load_telegram_config,
    send_strategy_report, send_text_message,
)
from lib.encoding_fix import ensure_utf8_output
ensure_utf8_output()

# ============================================================
# Logging
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger('daily_pipeline')

# Also log to file
_log_dir = PROJECT_ROOT / 'logs'
_log_dir.mkdir(exist_ok=True)
_fh = logging.FileHandler(
    _log_dir / f"pipeline_{datetime.now().strftime('%Y%m%d')}.log",
    encoding='utf-8',
)
_fh.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s'))
logger.addHandler(_fh)


# ============================================================
# Constants
# ============================================================
STRATEGY_ORDER = [
    'prices',
    'market_pulse',
    'stage2',
    'vcp',
    'bottom_fisher',
    'buying_checklist',
]

STRATEGY_SCRIPTS = {
    'prices':           'scripts/save_prices_yfinance.py',
    'market_pulse':     'scripts/market_pulse.py',
    'stage2':           'scripts/stage2_monitor.py',
    'vcp':              'scripts/vcp_scanner.py',
    'bottom_fisher':    'scripts/bottom_fisher.py',
    'buying_checklist': 'scripts/buying_checklist.py',
}

# Strategies that have Telegram templates and should be pushed
NOTIFY_STRATEGIES = ['market_pulse', 'stage2', 'vcp', 'bottom_fisher']


# ============================================================
# Trading Day Detection
# ============================================================
def is_trading_day(date: datetime = None) -> bool:
    """
    Check if the given date is a US stock market trading day.
    Simple heuristic: weekday (Mon-Fri).
    Does not account for US holidays — acceptable for 95% accuracy.
    """
    if date is None:
        date = datetime.now()
    return date.weekday() < 5  # 0=Mon, 4=Fri


# ============================================================
# Phase 1: Data Ingestion
# ============================================================
def run_phase1_ingestion(date_str: str, force: bool = False) -> bool:
    """
    Phase 1: Fetch latest price data.
    Calls save_prices_yfinance.py as subprocess to maintain isolation.

    Returns True if completed successfully.
    """
    logger.info("=" * 60)
    logger.info("PHASE 1: DATA INGESTION")
    logger.info("=" * 60)

    strategy = 'prices'

    if not force and is_pipeline_step_completed(date_str, strategy):
        logger.info(f"[{strategy}] Already completed for {date_str}, skipping")
        return True

    record_pipeline_run(date_str, strategy, 'running')
    start_time = time.time()

    try:
        script_path = PROJECT_ROOT / STRATEGY_SCRIPTS[strategy]
        env = {**os.environ, 'PYTHONUTF8': '1'}
        result = subprocess.run(
            [sys.executable, str(script_path), '--mode', 'all'],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            env=env,
            timeout=600,  # 10 minute timeout
        )

        duration = time.time() - start_time

        if result.returncode == 0:
            logger.info(f"[{strategy}] Completed in {duration:.1f}s")
            record_pipeline_run(date_str, strategy, 'ok', duration=duration)
            return True
        else:
            error_msg = result.stderr[-500:] if result.stderr else 'Unknown error'
            logger.error(f"[{strategy}] Failed (exit code {result.returncode}): {error_msg}")
            record_pipeline_run(date_str, strategy, 'failed', error_msg=error_msg, duration=duration)
            return False

    except subprocess.TimeoutExpired:
        duration = time.time() - start_time
        logger.error(f"[{strategy}] Timeout after {duration:.1f}s")
        record_pipeline_run(date_str, strategy, 'failed', error_msg='Timeout', duration=duration)
        return False
    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"[{strategy}] Exception: {e}")
        record_pipeline_run(date_str, strategy, 'failed', error_msg=str(e), duration=duration)
        return False


# ============================================================
# Phase 2: Strategy Computation
# ============================================================
def run_phase2_strategies(date_str: str, force: bool = False) -> dict:
    """
    Phase 2: Run all strategy scripts sequentially.
    Each script reads from DB and writes results back to DB.

    Returns dict: {strategy_name: 'ok'|'failed'|'skipped'}
    """
    logger.info("=" * 60)
    logger.info("PHASE 2: STRATEGY COMPUTATION")
    logger.info("=" * 60)

    results = {}
    # Skip 'prices' — already done in Phase 1
    strategies = [s for s in STRATEGY_ORDER if s != 'prices']

    for strategy in strategies:
        if not force and is_pipeline_step_completed(date_str, strategy):
            logger.info(f"[{strategy}] Already completed for {date_str}, skipping")
            results[strategy] = 'skipped'
            continue

        record_pipeline_run(date_str, strategy, 'running')
        start_time = time.time()

        try:
            script_path = PROJECT_ROOT / STRATEGY_SCRIPTS[strategy]
            env = {**os.environ, 'PYTHONUTF8': '1'}
            result = subprocess.run(
                [sys.executable, str(script_path), '--cron'],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                env=env,
                timeout=300,  # 5 minute timeout per strategy
            )

            duration = time.time() - start_time

            if result.returncode == 0:
                logger.info(f"[{strategy}] Completed in {duration:.1f}s")
                record_pipeline_run(date_str, strategy, 'ok', duration=duration)
                results[strategy] = 'ok'
            else:
                error_msg = result.stderr[-500:] if result.stderr else 'Unknown error'
                logger.error(f"[{strategy}] Failed: {error_msg}")
                record_pipeline_run(date_str, strategy, 'failed', error_msg=error_msg, duration=duration)
                results[strategy] = 'failed'

        except subprocess.TimeoutExpired:
            duration = time.time() - start_time
            logger.error(f"[{strategy}] Timeout after {duration:.1f}s")
            record_pipeline_run(date_str, strategy, 'failed', error_msg='Timeout', duration=duration)
            results[strategy] = 'failed'
        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"[{strategy}] Exception: {e}")
            record_pipeline_run(date_str, strategy, 'failed', error_msg=str(e), duration=duration)
            results[strategy] = 'failed'

    return results


# ============================================================
# Phase 3: Notification — Build context from DB + push
# ============================================================
def _build_market_pulse_context(date_str: str) -> dict:
    """Build template context for Market Pulse from DB data."""
    pulse_list = get_market_pulse(date_str=date_str)
    if not pulse_list:
        return {}

    pulse = pulse_list[0]
    index_data = pulse.get('index_data', {})
    breadth_data = pulse.get('breadth_data', {})

    # Rebuild regime_info
    regime = pulse['regime']
    regime_map = {
        'bullish': ('🟢', 'BULLISH', 'Trending strong, look for entries'),
        'neutral': ('🟡', 'NEUTRAL', 'Direction unclear, manage position size'),
        'cautious': ('🟠', 'CAUTIOUS', 'Weak market, reduce new positions'),
        'bearish': ('🔴', 'BEARISH', 'Downtrend, cash is king'),
    }
    regime_emoji, regime_label, hint = regime_map.get(regime, ('❓', regime.upper(), ''))

    # Previous pulse for regime change detection
    from lib.db import get_db
    with get_db() as conn:
        prev_row = conn.execute(
            "SELECT regime FROM market_pulse WHERE date < ? ORDER BY date DESC LIMIT 1",
            (date_str,)
        ).fetchone()
    prev_regime = prev_row['regime'] if prev_row else 'unknown'
    prev_regime_emojis = {'bullish': '🟢', 'neutral': '🟡', 'cautious': '🟠', 'bearish': '🔴'}

    # Build indices list
    indices = []
    for ticker in ['SPY', 'QQQ', 'IWM']:
        idx = index_data.get(ticker)
        if idx:
            indices.append(idx)

    vix = index_data.get('VIX')

    # Hot sectors from breadth
    hot_sectors = []
    if breadth_data:
        hot_sectors = [s for s in breadth_data.get('sector_ranking', []) if s.get('stage2', 0) > 0]

    return dict(
        timestamp=datetime.now().strftime('%m/%d %H:%M'),
        composite=pulse['composite_score'],
        scores=pulse.get('component_scores', {}),
        regime=regime,
        regime_emoji=regime_emoji,
        regime_label=regime_label,
        hint=hint,
        regime_changed=(prev_regime != regime and prev_regime != 'unknown'),
        prev_regime=prev_regime,
        prev_regime_emoji=prev_regime_emojis.get(prev_regime, '❓'),
        indices=indices,
        vix=vix,
        breadth=breadth_data if breadth_data else None,
        hot_sectors=hot_sectors,
    )


def _build_stage2_context(date_str: str) -> dict:
    """Build template context for Stage 2 Monitor from DB data."""
    import json

    results = get_strategy_results('stage2', date_str=date_str, limit=500)
    if not results:
        return {}

    # Get signal changes for today
    changes_raw = get_signal_changes(strategy='stage2', date_str=date_str, limit=100)

    # Get strategy states for entry date info
    states = get_strategy_states('stage2')
    state_map = {s['symbol']: s for s in states}

    stage2_stocks = []
    near_stocks = []

    for r in results:
        metrics = r.get('metrics', {})
        item = {
            'ticker': r['symbol'],
            'name': metrics.get('name', r['symbol']),
            'sector': metrics.get('sector', ''),
            'price': metrics.get('price', 0),
            'is_stage2': bool(r['is_signal']),
            'passed': r['passed'],
            'total': r['total'],
            'trend_power': r['score'],
            'conditions': r.get('conditions', {}),
            'condition_details': r.get('condition_details', {}),
            'pct_from_high': metrics.get('pct_from_high'),
            'support_sma50': metrics.get('sma50'),
            'support_sma150': metrics.get('sma150'),
            'vol_signal': metrics.get('vol_signal', ''),
            'stock_return_6m': metrics.get('stock_return_6m'),
            'chg_5d': metrics.get('chg_5d'),
            'chg_20d': metrics.get('chg_20d'),
        }

        # Days in Stage 2
        st = state_map.get(r['symbol'], {})
        days_in = 0
        if st.get('is_active') and st.get('entry_date'):
            try:
                days_in = (datetime.now() - datetime.strptime(st['entry_date'], '%Y-%m-%d')).days
            except Exception:
                pass
        item['days_in_stage2'] = days_in

        if r['is_signal']:
            stage2_stocks.append(item)
        elif r['passed'] >= 5:
            near_stocks.append(item)

    stage2_stocks.sort(key=lambda x: x.get('trend_power', 0), reverse=True)
    near_stocks.sort(key=lambda x: x['passed'], reverse=True)

    # Build changes list
    changes = []
    for c in changes_raw:
        details = c.get('details', {})
        change_item = {
            'ticker': c['symbol'],
            'type': 'entry' if c['change_type'] in ('entry', 'new_signal') else 'exit',
            'price': c.get('price'),
            'trend_power': c.get('score'),
            'pct_from_high': details.get('pct_from_high'),
            'stock_return_6m': details.get('stock_return_6m'),
            'days_held': details.get('days_held'),
            'failed_conditions': details.get('failed_conditions', []),
            'condition_details': details.get('condition_details', {}),
        }
        changes.append(change_item)

    # Get SPY 6M return from metrics
    spy_return_6m = None
    for r in results:
        m = r.get('metrics', {})
        if m.get('spy_return_6m') is not None:
            spy_return_6m = m['spy_return_6m']
            break

    return dict(
        timestamp=datetime.now().strftime('%m/%d %H:%M'),
        total_analyzed=len(results),
        spy_return_6m=spy_return_6m,
        stage2_stocks=stage2_stocks,
        near_stocks=near_stocks,
        changes=changes,
    )


def _build_vcp_context(date_str: str) -> dict:
    """Build template context for VCP Scanner from DB data."""
    results = get_strategy_results('vcp', date_str=date_str, limit=500)
    if not results:
        return {}

    changes_raw = get_signal_changes(strategy='vcp', date_str=date_str, limit=100)

    vcp_stocks = []
    near_vcp = []

    for r in results:
        metrics = r.get('metrics', {})
        item = {
            'ticker': r['symbol'],
            'name': metrics.get('name', r['symbol']),
            'sector': metrics.get('sector', ''),
            'price': metrics.get('price', 0),
            'is_vcp': bool(r['is_signal']),
            'vcp_score': r['score'],
            'passed': r['passed'],
            'total': r['total'],
            'conditions': r.get('conditions', {}),
            'condition_details': r.get('condition_details', {}),
            'days_in_stage2': metrics.get('days_in_stage2', 0),
            'sma10': metrics.get('sma10'),
            'sma50': metrics.get('sma50'),
            'chg_5d': metrics.get('chg_5d'),
            'chg_20d': metrics.get('chg_20d'),
            'metrics': metrics,
        }

        if r['is_signal']:
            vcp_stocks.append(item)
        elif r['passed'] >= 3:
            near_vcp.append(item)

    vcp_stocks.sort(key=lambda x: x.get('vcp_score', 0), reverse=True)
    near_vcp.sort(key=lambda x: x['passed'], reverse=True)

    changes = []
    for c in changes_raw:
        changes.append({
            'ticker': c['symbol'],
            'type': 'new_vcp' if c['change_type'] in ('entry', 'new_signal') else 'lost_vcp',
            'vcp_score': c.get('score'),
        })

    return dict(
        timestamp=datetime.now().strftime('%m/%d %H:%M'),
        total_analyzed=len(results),
        vcp_stocks=vcp_stocks,
        near_vcp=near_vcp,
        changes=changes,
    )


def _build_bottom_fisher_context(date_str: str) -> dict:
    """Build template context for Bottom Fisher from DB data."""
    results = get_strategy_results('bottom_fisher', date_str=date_str, limit=500)
    if not results:
        return {}

    changes_raw = get_signal_changes(strategy='bottom_fisher', date_str=date_str, limit=100)

    signal_stocks = []
    near_stocks = []

    for r in results:
        metrics = r.get('metrics', {})
        item = {
            'ticker': r['symbol'],
            'name': metrics.get('name', r['symbol']),
            'sector': metrics.get('sector', ''),
            'price': metrics.get('price', 0),
            'is_bottom_signal': bool(r['is_signal']),
            'bf_score': r['score'],
            'passed': r['passed'],
            'total': r['total'],
            'conditions': r.get('conditions', {}),
            'condition_details': r.get('condition_details', {}),
            'metrics': {
                'pct_from_52w_high': metrics.get('pct_from_high',
                    # Calculate from week52_high if available
                    round((metrics.get('price', 0) / metrics['week52_high'] - 1) * 100, 1)
                    if metrics.get('week52_high') else None
                ),
                'rsi': metrics.get('rsi'),
                'vol_ratio': metrics.get('vol_ratio'),
                'rsi_oversold': metrics.get('rsi_oversold', False),
                'rsi_divergence': metrics.get('rsi_divergence', False),
                'macd_divergence': metrics.get('macd_divergence', False),
                'candle_pattern': metrics.get('candle_pattern'),
            },
        }

        if r['is_signal']:
            signal_stocks.append(item)
        elif r['passed'] >= 4:  # near_signal_min
            near_stocks.append(item)

    signal_stocks.sort(key=lambda x: x.get('bf_score', 0), reverse=True)
    near_stocks.sort(key=lambda x: x['passed'], reverse=True)

    changes = []
    for c in changes_raw:
        changes.append({
            'ticker': c['symbol'],
            'type': 'new_signal' if c['change_type'] in ('entry', 'new_signal') else 'lost_signal',
            'bf_score': c.get('score'),
        })

    return dict(
        timestamp=datetime.now().strftime('%m/%d %H:%M'),
        total_analyzed=len(results),
        signal_stocks=signal_stocks,
        near_stocks=near_stocks,
        changes=changes,
    )


def _build_daily_summary(date_str: str, pipeline_results: dict) -> str:
    """Build a daily summary message with cross-strategy overview."""
    pulse_list = get_market_pulse(date_str=date_str)
    stage2_results = get_strategy_results('stage2', date_str=date_str, signal_only=True, limit=500)
    vcp_results = get_strategy_results('vcp', date_str=date_str, signal_only=True, limit=500)
    bf_results = get_strategy_results('bottom_fisher', date_str=date_str, signal_only=True, limit=500)
    today_changes = get_signal_changes(date_str=date_str, limit=200)

    # Regime
    regime_line = ""
    if pulse_list:
        p = pulse_list[0]
        regime_map = {'bullish': '🟢', 'neutral': '🟡', 'cautious': '🟠', 'bearish': '🔴'}
        emoji = regime_map.get(p['regime'], '❓')
        regime_line = f"{emoji} <b>{p['regime'].upper()}</b> ({p['composite_score']}/100)"
        if p.get('spy_price'):
            regime_line += f" · SPY ${p['spy_price']}"

    # Stage 2 count
    monitored = get_watchlist(enabled_only=True, source_type='monitored')
    total_monitored = len(monitored)
    s2_count = len(stage2_results)

    # New entries/exits
    new_entries = [c for c in today_changes if c['change_type'] in ('entry', 'new_signal')]
    exits = [c for c in today_changes if c['change_type'] in ('exit', 'lost_signal')]

    # Pipeline status
    failed_strategies = [k for k, v in pipeline_results.items() if v == 'failed']

    # Build message
    lines = [
        f"<b>📊 Daily Summary</b> — {date_str}",
        "",
    ]

    if regime_line:
        lines.append(f"🌡️ Market: {regime_line}")

    lines.append(f"📈 Stage 2: {s2_count}/{total_monitored}")

    if vcp_results:
        vcp_tickers = ', '.join(r['symbol'] for r in vcp_results[:5])
        lines.append(f"🎯 VCP Signals: {len(vcp_results)} — {vcp_tickers}")
    else:
        lines.append("🎯 VCP Signals: 0")

    if bf_results:
        bf_tickers = ', '.join(r['symbol'] for r in bf_results[:5])
        lines.append(f"🎣 Bottom Signals: {len(bf_results)} — {bf_tickers}")
    else:
        lines.append("🎣 Bottom Signals: 0")

    if new_entries:
        lines.append("")
        lines.append(f"<b>🔔 New Entries ({len(new_entries)})</b>")
        for c in new_entries[:10]:
            details = c.get('details', {})
            strategy_tag = c['strategy'][:3].upper()
            lines.append(f"  🟢 <b>{c['symbol']}</b> [{strategy_tag}] Score:{c.get('score', '?')}")

    if exits:
        lines.append("")
        lines.append(f"<b>🔴 Exits ({len(exits)})</b>")
        for c in exits[:10]:
            strategy_tag = c['strategy'][:3].upper()
            lines.append(f"  ⚪ <b>{c['symbol']}</b> [{strategy_tag}]")

    if failed_strategies:
        lines.append("")
        lines.append(f"⚠️ Failed: {', '.join(failed_strategies)}")

    lines.append("")
    lines.append("📋 Detailed reports follow ↓")

    return '\n'.join(lines)


# Context builders map
CONTEXT_BUILDERS = {
    'market_pulse': (_build_market_pulse_context, 'pulse_tg.j2', 'pulse_md.j2', '_pulse'),
    'stage2':       (_build_stage2_context,       'stage2_tg.j2', 'stage2_md.j2', ''),
    'vcp':          (_build_vcp_context,           'vcp_tg.j2',    'vcp_md.j2',    '_vcp'),
    'bottom_fisher': (_build_bottom_fisher_context, 'bottom_tg.j2', 'bottom_md.j2', '_bottom'),
}


def run_phase3_notification(
    date_str: str,
    notifier: TelegramNotifier,
    pipeline_results: dict,
    force: bool = False,
) -> dict:
    """
    Phase 3: Read from DB → Render templates → Push Telegram.

    Args:
        date_str: Date to send reports for
        notifier: TelegramNotifier instance
        pipeline_results: Phase 2 results dict {strategy: status}
        force: Ignore idempotent checks

    Returns:
        dict: {strategy: 'sent'|'failed'|'skipped'|'no_data'}
    """
    logger.info("=" * 60)
    logger.info("PHASE 3: NOTIFICATION")
    logger.info("=" * 60)

    results = {}

    # Step 1: Send daily summary first
    if force or not is_notification_sent(date_str, 'daily_summary'):
        try:
            summary_text = _build_daily_summary(date_str, pipeline_results)
            success = send_text_message(
                notifier, summary_text,
                strategy_name='daily_summary',
                notify_date=date_str,
            )
            results['daily_summary'] = 'sent' if success else 'failed'
            logger.info(f"[daily_summary] {'Sent' if success else 'Failed'}")
        except Exception as e:
            logger.error(f"[daily_summary] Error: {e}")
            results['daily_summary'] = 'failed'
    else:
        results['daily_summary'] = 'skipped'
        logger.info("[daily_summary] Already sent, skipping")

    # Brief delay between messages
    time.sleep(1)

    # Step 2: Send each strategy report
    for strategy in NOTIFY_STRATEGIES:
        if strategy not in CONTEXT_BUILDERS:
            continue

        # Skip if strategy computation failed and not forced
        phase2_status = pipeline_results.get(strategy, 'unknown')
        if phase2_status == 'failed' and not force:
            logger.warning(f"[{strategy}] Skipping notification — computation failed")
            results[strategy] = 'skipped'
            continue

        builder_func, tg_template, md_template, prefix = CONTEXT_BUILDERS[strategy]

        try:
            # Build context from DB
            ctx = builder_func(date_str)

            if not ctx:
                logger.info(f"[{strategy}] No data in DB for {date_str}")
                results[strategy] = 'no_data'
                continue

            # Send via notifier (with idempotent check inside)
            result = send_strategy_report(
                notifier=notifier,
                template_name=tg_template,
                context=ctx,
                strategy_name=strategy,
                notify_date=date_str,
                save_to_disk=True,
                strategy_prefix=prefix,
                md_template_name=md_template,
            )

            if result['error'] == 'already_sent':
                results[strategy] = 'skipped'
                logger.info(f"[{strategy}] Already sent, skipping")
            elif result['success']:
                results[strategy] = 'sent'
                logger.info(f"[{strategy}] Sent ({result['segments']} segments)")
            else:
                results[strategy] = 'failed'
                logger.error(f"[{strategy}] Failed: {result['error']}")

        except Exception as e:
            logger.error(f"[{strategy}] Notification error: {e}")
            results[strategy] = 'failed'
            record_notification(date_str, 'telegram', strategy, 'failed', error_msg=str(e))

        # Rate limiting between strategy reports
        time.sleep(1.5)

    return results


# ============================================================
# Main Pipeline
# ============================================================
def run_pipeline(args):
    """Main pipeline entry point."""
    date_str = datetime.now().strftime('%Y-%m-%d')
    logger.info(f"{'=' * 60}")
    logger.info(f"DAILY PIPELINE — {date_str}")
    logger.info(f"{'=' * 60}")

    # Initialize DB (ensures new tables exist)
    init_db()

    # Trading day check
    if not args.force and not args.notify_only and not is_trading_day():
        logger.info("Not a trading day (weekend). Use --force to override.")
        return

    # Setup notifier
    bot_token, chat_id = load_telegram_config()
    if not bot_token or not chat_id:
        if not args.no_notify:
            logger.warning(
                "Telegram not configured. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID "
                "in environment or .env file. Running without notifications."
            )
        notifier = None
    else:
        notifier = TelegramNotifier(
            bot_token=bot_token,
            chat_id=chat_id,
            dry_run=args.dry_run,
        )

    # Test bot connectivity
    if args.test_bot:
        if notifier:
            try:
                info = notifier.test_connection()
                logger.info(f"Bot test successful: {info}")
                # Send a test message
                test_msg = f"🤖 Stock Tracker bot test — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                notifier.send(test_msg)
                logger.info("Test message sent!")
            except Exception as e:
                logger.error(f"Bot test failed: {e}")
        else:
            logger.error("Cannot test: Telegram not configured")
        return

    pipeline_results = {}

    # Phase 1 + 2: Data ingestion + Strategy computation
    if not args.notify_only:
        # Phase 1
        prices_ok = run_phase1_ingestion(date_str, force=args.force)
        pipeline_results['prices'] = 'ok' if prices_ok else 'failed'

        if not prices_ok and not args.force:
            logger.warning("Price ingestion failed. Continuing with strategies...")

        # Phase 2
        strategy_results = run_phase2_strategies(date_str, force=args.force)
        pipeline_results.update(strategy_results)
    else:
        # notify-only mode: check what was already computed
        runs = get_pipeline_runs(date_str)
        for run in runs:
            pipeline_results[run['strategy']] = run['status']
        logger.info(f"Notify-only mode. Previous runs: {pipeline_results}")

    # Phase 3: Notification
    if not args.no_notify and notifier:
        notify_results = run_phase3_notification(
            date_str, notifier, pipeline_results, force=args.force,
        )
        logger.info(f"Notification results: {notify_results}")
    elif args.no_notify:
        logger.info("Notifications disabled (--no-notify)")
    else:
        logger.info("Notifications skipped (Telegram not configured)")

    # Final summary
    logger.info("=" * 60)
    logger.info("PIPELINE COMPLETE")
    logger.info(f"  Date: {date_str}")
    for strategy, status in pipeline_results.items():
        emoji = {'ok': '✅', 'failed': '❌', 'skipped': '⏭️'}.get(status, '❓')
        logger.info(f"  {emoji} {strategy}: {status}")
    logger.info("=" * 60)


# ============================================================
# CLI
# ============================================================
def parse_args():
    parser = argparse.ArgumentParser(
        description="Stock Tracker Daily Pipeline — Three-phase data update + Telegram notification"
    )
    parser.add_argument(
        '--notify-only', action='store_true',
        help='Skip data update, only send notifications from existing DB data'
    )
    parser.add_argument(
        '--no-notify', action='store_true',
        help='Run data update but skip Telegram notifications'
    )
    parser.add_argument(
        '--dry-run', action='store_true',
        help='Render messages but do not actually send to Telegram'
    )
    parser.add_argument(
        '--force', action='store_true',
        help='Force re-run all steps, ignoring idempotent checks'
    )
    parser.add_argument(
        '--test-bot', action='store_true',
        help='Test Telegram bot connectivity and send a test message'
    )
    return parser.parse_args()


if __name__ == '__main__':
    args = parse_args()
    try:
        run_pipeline(args)
    except KeyboardInterrupt:
        logger.info("Pipeline interrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.critical(f"Pipeline failed with unhandled error: {e}", exc_info=True)
        sys.exit(1)
