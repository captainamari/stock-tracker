"""XNYS regular sessions (including early closes), all clock comparisons in UTC."""
from datetime import timedelta
from functools import lru_cache
import pandas as pd
import exchange_calendars as xcals
from lib.settings import settings, utcnow


@lru_cache(maxsize=8)
def calendar(year):
    return xcals.get_calendar(settings().calendar, start=f'{year-5}-01-01', end=f'{year+2}-12-31')


def is_trading_day(day):
    day = pd.Timestamp(day).date()
    return calendar(day.year).is_session(str(day))


def completed_session(now=None):
    now = pd.Timestamp(now or utcnow())
    if now.tzinfo is None:
        raise ValueError('Clock must be timezone-aware')
    local = now.tz_convert(settings().market_timezone)
    cal = calendar(local.year)
    day = cal.date_to_session(local.date().isoformat(), direction='previous')
    if cal.session_close(day) > now:
        day = cal.previous_session(day)
    return day.date().isoformat()


def sessions(start, end):
    end = pd.Timestamp(end).date()
    return calendar(end.year).sessions_in_range(str(start), str(end)).strftime('%Y-%m-%d').tolist()


def week_complete(day):
    day = pd.Timestamp(day).date()
    friday = day + timedelta(days=4-day.weekday())
    return calendar(day.year).date_to_session(str(friday), direction='previous').date() <= day
