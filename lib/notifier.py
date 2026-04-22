"""
Stock Tracker — Telegram Notification Engine
==============================================
Provides robust Telegram push capabilities for daily strategy reports.

Features:
  - Bot API wrapper with auto-retry and exponential backoff
  - Auto message splitting for Telegram's 4096-char limit
  - HTML → plain text fallback on parse errors
  - Idempotent push via notification_log DB table
  - Template rendering integration with lib/report.py

Usage:
    from lib.notifier import TelegramNotifier, send_strategy_report

    notifier = TelegramNotifier(bot_token="...", chat_id="...")
    notifier.send("Hello <b>World</b>")

    # High-level: render template + push + optional disk save
    send_strategy_report(notifier, 'pulse_tg.j2', context_dict)
"""

import os
import time
import json
import logging
import urllib.request
import urllib.error
import urllib.parse
from typing import Optional, List, Dict, Any, Tuple
from pathlib import Path

from lib.report import render_template, split_telegram_message, save_reports

logger = logging.getLogger(__name__)

# ============================================================
# Configuration
# ============================================================
def load_telegram_config() -> Tuple[Optional[str], Optional[str]]:
    """
    Load Telegram Bot Token and Chat ID from environment variables
    or .env file.

    Priority:
      1. Environment variables: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
      2. .env file in project root

    Returns:
        (bot_token, chat_id) — both may be None if not configured
    """
    bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat_id = os.environ.get('TELEGRAM_CHAT_ID')

    if bot_token and chat_id:
        return bot_token, chat_id

    # Try loading from .env file
    env_file = Path(__file__).parent.parent / '.env'
    if env_file.exists():
        try:
            with open(env_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    if '=' in line:
                        key, _, value = line.partition('=')
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")
                        if key == 'TELEGRAM_BOT_TOKEN' and not bot_token:
                            bot_token = value
                        elif key == 'TELEGRAM_CHAT_ID' and not chat_id:
                            chat_id = value
        except Exception as e:
            logger.warning(f"Failed to read .env file: {e}")

    return bot_token, chat_id


# ============================================================
# Telegram Bot API Client
# ============================================================
class TelegramNotifier:
    """
    Telegram Bot API wrapper with retry, splitting, and fallback.

    Args:
        bot_token: Telegram Bot API token
        chat_id: Target chat/channel ID
        max_retries: Max retry attempts per message segment
        retry_delay: Base delay (seconds) for exponential backoff
        dry_run: If True, log messages instead of actually sending
    """

    TELEGRAM_MAX_LEN = 4000  # Leave margin under 4096 limit

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        max_retries: int = 3,
        retry_delay: float = 2.0,
        dry_run: bool = False,
    ):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.dry_run = dry_run
        self.api_base = f"https://api.telegram.org/bot{bot_token}"

    def send(self, text: str, parse_mode: str = "HTML") -> List[Optional[str]]:
        """
        Send a message, auto-splitting if needed.

        Returns:
            List of Telegram message IDs (str) for each segment,
            or None for failed segments.
        """
        parts = split_telegram_message(text, self.TELEGRAM_MAX_LEN)
        message_ids = []

        for i, part in enumerate(parts):
            if len(parts) > 1:
                logger.info(f"Sending segment {i+1}/{len(parts)} ({len(part)} chars)")

            msg_id = self._send_one(part, parse_mode)
            message_ids.append(msg_id)

            # Rate limiting between segments
            if i < len(parts) - 1:
                time.sleep(1.0)

        return message_ids

    def _send_one(self, text: str, parse_mode: str = "HTML") -> Optional[str]:
        """
        Send a single message segment with retry and fallback.

        Returns:
            Telegram message ID (str) if successful, None if all retries failed.
        """
        if self.dry_run:
            logger.info(f"[DRY RUN] Would send {len(text)} chars (parse_mode={parse_mode})")
            logger.debug(f"[DRY RUN] Content preview: {text[:200]}...")
            return "dry_run"

        for attempt in range(self.max_retries):
            try:
                result = self._call_api("sendMessage", {
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": True,
                })
                msg_id = str(result.get("message_id", ""))
                logger.info(f"Message sent successfully (id={msg_id})")
                return msg_id

            except TelegramAPIError as e:
                # If HTML parsing fails, try plain text fallback
                if "can't parse entities" in str(e).lower() and parse_mode == "HTML":
                    logger.warning(f"HTML parse error, falling back to plain text")
                    return self._send_one(self._strip_html(text), parse_mode="")

                # Rate limited — wait and retry
                if e.status_code == 429:
                    retry_after = e.retry_after or (self.retry_delay * (2 ** attempt))
                    logger.warning(f"Rate limited, waiting {retry_after}s")
                    time.sleep(retry_after)
                    continue

                # Other errors — retry with backoff
                delay = self.retry_delay * (2 ** attempt)
                logger.warning(
                    f"Send failed (attempt {attempt+1}/{self.max_retries}): {e}. "
                    f"Retrying in {delay}s..."
                )
                time.sleep(delay)

            except Exception as e:
                delay = self.retry_delay * (2 ** attempt)
                logger.error(
                    f"Unexpected error (attempt {attempt+1}/{self.max_retries}): {e}. "
                    f"Retrying in {delay}s..."
                )
                time.sleep(delay)

        logger.error(f"All {self.max_retries} attempts failed for message ({len(text)} chars)")
        return None

    def _call_api(self, method: str, params: Dict[str, Any]) -> Dict:
        """
        Call Telegram Bot API using urllib (no external HTTP dependency).
        """
        url = f"{self.api_base}/{method}"
        data = json.dumps(params).encode('utf-8')
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read().decode('utf-8'))
                if not body.get("ok"):
                    raise TelegramAPIError(
                        body.get("description", "Unknown error"),
                        status_code=body.get("error_code"),
                    )
                return body.get("result", {})

        except urllib.error.HTTPError as e:
            body_str = e.read().decode('utf-8', errors='replace')
            try:
                body = json.loads(body_str)
                desc = body.get("description", body_str)
                retry_after = body.get("parameters", {}).get("retry_after")
            except (json.JSONDecodeError, KeyError):
                desc = body_str
                retry_after = None
            raise TelegramAPIError(desc, status_code=e.code, retry_after=retry_after)

        except urllib.error.URLError as e:
            raise TelegramAPIError(f"Network error: {e.reason}")

    @staticmethod
    def _strip_html(text: str) -> str:
        """Strip HTML tags for plain text fallback."""
        import re
        clean = re.sub(r'<[^>]+>', '', text)
        clean = clean.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
        return clean

    def test_connection(self) -> Dict:
        """Test bot connectivity by calling getMe."""
        if self.dry_run:
            return {"ok": True, "dry_run": True}
        try:
            result = self._call_api("getMe", {})
            logger.info(f"Bot connected: @{result.get('username', '?')}")
            return result
        except Exception as e:
            logger.error(f"Bot connection test failed: {e}")
            raise


class TelegramAPIError(Exception):
    """Telegram Bot API error."""
    def __init__(self, message: str, status_code: Optional[int] = None,
                 retry_after: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


# ============================================================
# High-level: Send Strategy Report
# ============================================================
def send_strategy_report(
    notifier: TelegramNotifier,
    template_name: str,
    context: Dict[str, Any],
    strategy_name: str = "",
    notify_date: Optional[str] = None,
    save_to_disk: bool = True,
    strategy_prefix: str = "",
    md_template_name: Optional[str] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """
    High-level interface: render template → push Telegram → optional disk save.

    Args:
        notifier: TelegramNotifier instance
        template_name: Telegram template name (e.g. 'pulse_tg.j2')
        context: Template rendering context dict
        strategy_name: Strategy identifier for notification_log
        notify_date: Date string (YYYY-MM-DD), defaults to today
        save_to_disk: Whether to also save MD/TG files to reports/daily/
        strategy_prefix: File name prefix for save_reports()
        md_template_name: MD template name for disk save (e.g. 'pulse_md.j2')
        force: If True, skip idempotent check and re-send even if already sent

    Returns:
        {
            'success': bool,
            'message_ids': [str],
            'segments': int,
            'disk_saved': bool,
            'error': str | None,
        }
    """
    from lib.db import record_notification, is_notification_sent
    from datetime import datetime

    if notify_date is None:
        notify_date = datetime.now().strftime('%Y-%m-%d')

    result = {
        'success': False,
        'message_ids': [],
        'segments': 0,
        'disk_saved': False,
        'error': None,
    }

    # Idempotent check (skip when force=True)
    if not force and strategy_name and is_notification_sent(notify_date, strategy_name):
        logger.info(f"[{strategy_name}] Already sent for {notify_date}, skipping")
        result['success'] = True
        result['error'] = 'already_sent'
        return result

    if force and strategy_name:
        logger.info(f"[{strategy_name}] Force mode — re-sending for {notify_date}")

    # Render template
    try:
        tg_report = render_template(template_name, **context)
    except Exception as e:
        error_msg = f"Template render failed ({template_name}): {e}"
        logger.error(error_msg)
        result['error'] = error_msg
        if strategy_name:
            record_notification(notify_date, 'telegram', strategy_name, 'failed', error_msg=error_msg)
        return result

    # Send via Telegram
    try:
        message_ids = notifier.send(tg_report)
        success_ids = [mid for mid in message_ids if mid is not None]
        result['message_ids'] = success_ids
        result['segments'] = len(message_ids)

        if len(success_ids) == len(message_ids) and success_ids:
            # All segments sent successfully
            result['success'] = True
            if strategy_name:
                record_notification(
                    notify_date, 'telegram', strategy_name, 'sent',
                    message_id=','.join(success_ids),
                )
            logger.info(f"[{strategy_name}] Sent {len(success_ids)}/{len(message_ids)} segments")
        elif success_ids:
            # Partial success — some segments failed, mark as 'partial'
            # so re-run will retry (is_notification_sent only considers 'sent')
            result['success'] = True
            result['error'] = f'partial: {len(success_ids)}/{len(message_ids)} segments delivered'
            if strategy_name:
                record_notification(
                    notify_date, 'telegram', strategy_name, 'partial',
                    message_id=','.join(success_ids),
                    error_msg=f'{len(success_ids)}/{len(message_ids)} segments delivered',
                )
            logger.warning(
                f"[{strategy_name}] Partial send: {len(success_ids)}/{len(message_ids)} segments. "
                f"Will retry on next run."
            )
        else:
            result['error'] = 'All segments failed to send'
            if strategy_name:
                record_notification(
                    notify_date, 'telegram', strategy_name, 'failed',
                    error_msg='All segments failed',
                )

    except Exception as e:
        error_msg = f"Send failed: {e}"
        logger.error(f"[{strategy_name}] {error_msg}")
        result['error'] = error_msg
        if strategy_name:
            record_notification(notify_date, 'telegram', strategy_name, 'failed', error_msg=error_msg)

    # Optional disk save
    if save_to_disk:
        try:
            md_report = ""
            if md_template_name:
                md_report = render_template(md_template_name, **context)
            save_reports(md_report, tg_report, strategy_prefix=strategy_prefix)
            result['disk_saved'] = True
        except Exception as e:
            logger.warning(f"[{strategy_name}] Disk save failed: {e}")

    return result


def send_text_message(
    notifier: TelegramNotifier,
    text: str,
    strategy_name: str = "",
    notify_date: Optional[str] = None,
    force: bool = False,
) -> bool:
    """
    Send a plain text/HTML message (no template rendering).
    With idempotent check (skippable via force=True).

    Returns True if sent successfully.
    """
    from lib.db import record_notification, is_notification_sent
    from datetime import datetime

    if notify_date is None:
        notify_date = datetime.now().strftime('%Y-%m-%d')

    if not force and strategy_name and is_notification_sent(notify_date, strategy_name):
        logger.info(f"[{strategy_name}] Already sent for {notify_date}, skipping")
        return True

    if force and strategy_name:
        logger.info(f"[{strategy_name}] Force mode — re-sending for {notify_date}")

    try:
        message_ids = notifier.send(text)
        success_ids = [mid for mid in message_ids if mid is not None]
        total = len(message_ids)

        if len(success_ids) == total and success_ids:
            # All segments delivered
            if strategy_name:
                record_notification(
                    notify_date, 'telegram', strategy_name, 'sent',
                    message_id=','.join(str(m) for m in success_ids),
                )
            return True
        elif success_ids:
            # Partial delivery — mark as 'partial' so next run retries
            if strategy_name:
                record_notification(
                    notify_date, 'telegram', strategy_name, 'partial',
                    message_id=','.join(str(m) for m in success_ids),
                    error_msg=f'{len(success_ids)}/{total} segments delivered',
                )
            logger.warning(
                f"[{strategy_name}] Partial: {len(success_ids)}/{total} segments. Will retry."
            )
            return True
        else:
            if strategy_name:
                record_notification(
                    notify_date, 'telegram', strategy_name, 'failed',
                    error_msg='All segments failed',
                )
            return False
    except Exception as e:
        logger.error(f"[{strategy_name}] Send failed: {e}")
        if strategy_name:
            record_notification(notify_date, 'telegram', strategy_name, 'failed', error_msg=str(e))
        return False
