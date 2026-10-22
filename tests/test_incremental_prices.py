"""Request-range regressions through the worker, using no external services.

Prices are anchored to absolute dates, so requesting a smaller range does not
change the synthetic value of the overlap bar (unlike start-relative fixtures).
"""
from datetime import date, datetime, timedelta, timezone

import pytest

from lib import db
from lib.prices import read_prices
from lib.queries import report_data, ticker_data
from tests.fixtures import bars, seed_watchlist, update

OHLC = ['Open', 'High', 'Low', 'Close']


class Source:
    def __init__(self):
        self.frame = bars('AAA', '2024-08-01', '2027-01-04')
        self.calls = []

    def __call__(self, symbol, start, target):
        self.calls.append((symbol, start, target))
        return self.frame.loc[start:target].copy()

    def ranges(self):
        return [(start, target) for symbol, start, target in self.calls if symbol == 'AAA']


@pytest.fixture
def source(database):
    seed_watchlist()
    return Source()


def collect(source, target):
    return update(source, datetime.fromisoformat(target).replace(hour=23, tzinfo=timezone.utc))


def history_start(target):
    return str(date.fromisoformat(target) - timedelta(days=800))


def stored(watermark=None):
    with db.get_db() as conn:
        return read_prices(conn, 'AAA', '2027-01-04', watermark)


def test_bootstrap_then_daily_increment_and_same_day_rerun(source):
    collect(source, '2026-10-20')
    assert source.ranges() == [(history_start('2026-10-20'), '2026-10-20')]
    before = stored()
    source.calls.clear()
    run = collect(source, '2026-10-21')
    assert source.ranges() == [('2026-10-20', '2026-10-21')]
    after = stored()
    assert after[:-1] == before
    assert after[-1]['date'] == '2026-10-21' and after[-1]['run_id'] == run
    assert ticker_data('AAA')['asset']['status'] == 'ok'
    source.calls.clear()
    collect(source, '2026-10-21')
    assert source.ranges() == [('2026-10-21', '2026-10-21')]
    assert stored() == after  # No duplicate price revisions on a same-day run.


@pytest.mark.parametrize('previous,target', [
    ('2026-10-16', '2026-10-19'),  # Weekend is not a history gap.
    ('2026-12-24', '2026-12-28'),  # Christmas and weekend.
    ('2026-10-02', '2026-10-21'),  # Several missed updates are one increment.
])
def test_calendar_and_missed_updates_only_fetch_the_unsaved_tail(source, previous, target):
    collect(source, previous)
    source.calls.clear()
    collect(source, target)
    assert source.ranges() == [(previous, target)]
    assert ticker_data('AAA')['asset']['actual_date'] == target
    assert ticker_data('AAA')['asset']['status'] == 'ok'


def test_short_contiguous_ipo_history_does_not_bootstrap_again(source):
    source.frame = source.frame.loc['2026-09-21':]
    collect(source, '2026-10-20')
    assert len(stored()) < 252
    source.calls.clear()
    collect(source, '2026-10-21')
    assert source.ranges() == [('2026-10-20', '2026-10-21')]
    asset = ticker_data('AAA')
    assert asset['asset']['status'] == 'ok'
    assert asset['strategies']['stage2_us']['status'] == 'insufficient_data'


@pytest.mark.parametrize('damage', ['missing', 'invalid_ohlc', 'missing_volume'])
def test_real_history_gaps_expand_and_repair(source, damage):
    original = source.frame.copy()
    if damage == 'missing':
        source.frame = source.frame.drop('2026-09-01')
    elif damage == 'invalid_ohlc':
        source.frame.loc['2026-09-01', 'High'] = 1
    else:
        source.frame.loc['2026-09-01', 'Volume'] = float('nan')
    collect(source, '2026-10-20')
    assert ticker_data('AAA')['asset']['status'] == 'insufficient_data'
    source.frame = original
    source.calls.clear()
    collect(source, '2026-10-21')
    assert source.ranges() == [(history_start('2026-10-21'), '2026-10-21')]
    assert ticker_data('AAA')['asset']['status'] == 'ok'


def test_missing_new_session_stays_stale_without_full_downloads(source):
    collect(source, '2026-10-20')
    before = stored()
    source.frame = source.frame.loc[:'2026-10-20']
    for target in ('2026-10-21', '2026-10-22'):
        source.calls.clear()
        collect(source, target)
        assert source.ranges() == [('2026-10-20', target)]
        assert ticker_data('AAA')['asset']['status'] == 'stale'
        assert stored() == before


@pytest.mark.parametrize('field', OHLC)
def test_adjusted_overlap_change_expands_and_keeps_old_publication(source, field):
    first = collect(source, '2026-10-20')
    old_report = report_data(first)['body']
    before = stored()
    watermark = max(r['id'] for r in before)
    # A retrospective correction can affect an OHLC field without changing close.
    source.frame.loc[:'2026-10-20', field] += .1
    source.calls.clear()
    collect(source, '2026-10-21')
    assert source.ranges() == [('2026-10-20', '2026-10-21'), (history_start('2026-10-21'), '2026-10-21')]
    with db.get_db() as conn:
        assert read_prices(conn, 'AAA', '2026-10-20', watermark) == before
    assert report_data(first)['body'] == old_report
    updated = {r['date']:r for r in stored()}
    assert updated['2026-09-01'][field.lower()] == pytest.approx(source.frame.loc['2026-09-01', field])


@pytest.mark.parametrize('action,value,factor', [('Dividends', .5, .99), ('Stock Splits', 2., .5)])
def test_new_corporate_action_expands_once_even_if_overlap_is_unchanged(source, action, value, factor):
    collect(source, '2026-10-20')
    oldest = stored()[0]['date']
    source.frame[action] = 0.
    source.frame.loc['2026-10-21', action] = value
    source.calls.clear()
    collect(source, '2026-10-21')
    assert source.ranges() == [('2026-10-20', '2026-10-21'), (history_start('2026-10-21'), '2026-10-21')]
    source.calls.clear()
    collect(source, '2026-10-21')
    assert source.ranges() == [('2026-10-21', '2026-10-21')]
    # A late adjustment on the now-known action day still invalidates history.
    source.frame[OHLC] *= factor
    source.calls.clear()
    collect(source, '2026-10-22')
    assert source.ranges() == [('2026-10-21', '2026-10-22'), (oldest, '2026-10-22')]
    assert stored()[0]['close'] == pytest.approx(source.frame.loc[oldest, 'Close'])
    assert ticker_data('AAA')['asset']['status'] == 'ok'


def test_volume_correction_is_saved_without_expanding_history(source):
    collect(source, '2026-10-20')
    source.frame.loc['2026-10-20', 'Volume'] += 100
    source.calls.clear()
    collect(source, '2026-10-21')
    assert source.ranges() == [('2026-10-20', '2026-10-21')]
    assert stored()[-2]['volume'] == source.frame.loc['2026-10-20', 'Volume']


def test_source_omits_saved_overlap_is_checked_and_tombstoned(source):
    collect(source, '2026-10-20')
    source.frame = source.frame.drop('2026-10-20')
    source.calls.clear()
    collect(source, '2026-10-21')
    assert source.ranges() == [('2026-10-20', '2026-10-21'), (history_start('2026-10-21'), '2026-10-21')]
    assert stored()[-2]['quality'] == 'source_missing'
    assert ticker_data('AAA')['asset']['status'] == 'insufficient_data'


def test_failed_expanded_request_does_not_commit_partially_adjusted_prices(source):
    first = collect(source, '2026-10-20')
    before = stored()
    old_report = report_data(first)['body']
    source.frame[OHLC] *= .5
    source.calls.clear()
    def fails_full(symbol, start, target):
        frame = source(symbol, start, target)
        if start == history_start(target):
            raise RuntimeError('Synthetic full-window failure')
        return frame
    collect(fails_full, '2026-10-21')
    assert source.ranges() == [('2026-10-20', '2026-10-21'), (history_start('2026-10-21'), '2026-10-21')]
    assert stored() == before
    assert ticker_data('AAA')['asset']['status'] == 'failed'
    assert report_data(first)['body'] == old_report
