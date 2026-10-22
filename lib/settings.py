"""Central runtime configuration. Secrets never enter public responses."""
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]


def utcnow():
    return datetime.now(timezone.utc)


def stamp():
    return utcnow().isoformat()


@dataclass(frozen=True)
class Settings:
    database: Path = field(default_factory=lambda: Path(os.getenv('STOCK_DB', ROOT / 'data/stock_tracker.db')))
    market_timezone: str = 'America/New_York'
    display_timezone: str = field(default_factory=lambda: os.getenv('DISPLAY_TIMEZONE', 'Asia/Shanghai'))
    calendar: str = 'XNYS'
    update_time: str = '04:00'
    notify_time: str = '06:00'
    history_days: int = 800
    revision_lookback_days: int = 45
    lease_seconds: int = 90
    index_universe_enabled: bool = field(default_factory=lambda: os.getenv('INDEX_UNIVERSE_ENABLED', 'true').lower() == 'true')
    yahoo_min_interval_seconds: float = field(default_factory=lambda: float(os.getenv('YAHOO_MIN_INTERVAL_SECONDS', '5')))
    yahoo_cooldown_seconds: int = field(default_factory=lambda: int(os.getenv('YAHOO_COOLDOWN_SECONDS', '21600')))
    secure_cookies: bool = field(default_factory=lambda: os.getenv('COOKIE_SECURE', 'true').lower() == 'true')
    public_url: str = field(default_factory=lambda: os.getenv('PUBLIC_URL', 'http://127.0.0.1:8000').rstrip('/'))
    hub_url: str = field(default_factory=lambda: os.getenv('NOTIFICATION_API_URL', '').rstrip('/'))
    hub_token: str = field(default_factory=lambda: os.getenv('NOTIFICATION_API_TOKEN', ''))

    def __post_init__(self):
        ZoneInfo(self.display_timezone)
        if not 1 <= self.yahoo_min_interval_seconds <= 3600 or self.yahoo_cooldown_seconds < 3600:
            raise ValueError('Yahoo pacing must be 1..3600 seconds; cooldown at least 3600 seconds')


def settings():
    return Settings()
