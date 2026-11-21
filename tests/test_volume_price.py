import copy
import json

import numpy as np
import pandas as pd
import pytest

from lib.market_calendar import calendar
from lib.volume_price import analyze, load_parameters, summary


def frame(target='2026-10-20', direction=1):
    cal = calendar(int(target[:4]))
    dates = cal.sessions[cal.sessions <= pd.Timestamp(target)][-90:]
    close = 100*np.power(1+direction*.005, np.arange(len(dates)))
    return pd.DataFrame(dict(Open=close, High=close*1.01, Low=close*.99,
                             Close=close, Volume=100.0), index=dates)


def pattern(direction=1, order=None):
    data = frame(direction=direction)
    moves = order or [1,1,-1,1,-1,1,-1,1,-1,-1]
    for i, move in enumerate(moves, len(data)-10):
        data.iloc[i, data.columns.get_loc('Close')] = data.Close.iloc[i-1]*(1+direction*move*.01)
        data.iloc[i, data.columns.get_loc('Volume')] = 200 if move > 0 else 50
    return data


@pytest.mark.parametrize('direction,confirmation,sequence,trend',[
    (1,'bullish','pullback','up'), (-1,'bearish','rebound','down')])
def test_multiday_evidence_and_order(direction, confirmation, sequence, trend):
    result = analyze(pattern(direction), '2026-10-20')
    assert result['status'] == 'ok'
    assert result['confirmation'] == confirmation and result['price_trend'] == trend
    assert result['sequence'] == sequence and result['sequence_days'] == 2
    assert result['up_down_volume_ratio'] == (4 if direction == 1 else .25)
    assert sum(result['counts'].values()) == 10
    assert len(result['observations']) == 10
    assert result['parameters'] == load_parameters()
    json.dumps(result, allow_nan=False)


def test_same_counts_do_not_claim_same_order():
    first = analyze(pattern(), '2026-10-20')
    second = analyze(pattern(order=[-1,-1,-1,-1,-1,1,1,1,1,1]), '2026-10-20')
    assert first['counts'] == second['counts']
    assert first['sequence'] == 'pullback' and second['sequence'] == 'none'


def test_baseline_excludes_current_day_and_future_bars():
    data = frame()
    data.iloc[-1, data.columns.get_loc('Volume')] = 200
    future = data.iloc[[-1]].copy()
    future.index = pd.DatetimeIndex(['2026-10-21'])
    future['Volume'] = 1e8
    result = analyze(pd.concat([data,future]), '2026-10-20')
    assert result['today']['rvol'] == 2
    assert result['confirmation'] == 'unknown'  # No down-day sample.
    assert result['up_down_volume_ratio'] is None


@pytest.mark.parametrize('bad', [0, -1, np.nan, np.inf])
def test_bad_volume_cannot_be_classified_as_low(bad):
    data = pattern()
    data.iloc[-1, data.columns.get_loc('Volume')] = bad
    result = analyze(data, '2026-10-20')
    assert result['today']['state'] == 'unknown'
    assert result['confirmation'] == 'unknown'
    json.dumps(result, allow_nan=False)


def test_calendar_gap_invalidates_daily_move_and_baseline():
    data = pattern().drop(pattern().index[-3])
    result = analyze(data, '2026-10-20')
    assert result['status'] == 'partial' and result['confirmation'] == 'unknown'
    assert result['observations'][-2]['reason'] == 'missing_price'
    assert result['today']['rvol'] is None
    assert result['price_trend'] == 'unknown'


def test_early_close_not_misclassified_or_in_baseline():
    data = frame('2026-11-27')
    data.iloc[-1, data.columns.get_loc('Volume')] = 20
    result = analyze(data, '2026-11-27')
    assert result['today']['reason'] == 'early_close'
    assert result['today']['state'] == 'unknown'
    following = data.iloc[[-1]].copy()
    following.index = pd.DatetimeIndex(['2026-11-30'])
    following['Volume'] = 100
    result = analyze(pd.concat([data,following]), '2026-11-30')
    assert result['today']['rvol'] == 1
    assert result['confirmation'] == 'unknown'  # window contains excluded session


def test_short_history_flat_and_parameter_fingerprint():
    data = frame()
    data.loc[data.index[-1], 'Close'] = data.Close.iloc[-2]
    result = analyze(data,'2026-10-20')
    assert result['today']['state'] == 'flat'
    assert analyze(data.tail(5),'2026-10-20')['today']['state'] == 'unknown'
    p = load_parameters();p['high_volume'] = 1.5
    revised = analyze(data,'2026-10-20',p)
    assert revised['parameter_id'] != result['parameter_id']
    assert '旧批次' in summary(None)


@pytest.mark.parametrize('changes', [{'version':True}, {'high_volume':.9}, {'low_volume':2},
                                    {'trend_fast':60}, {'window_sessions':True},
                                    {'min_side_days':6}, {'unexpected':1}])
def test_bad_configuration_fails_clearly(tmp_path, changes):
    p=load_parameters();p.update(changes)
    path=tmp_path/'bad.json';path.write_text(json.dumps(p))
    with pytest.raises(ValueError):load_parameters(path)


def test_notification_top10_eligibility_ties_and_legacy():
    from lib.daily_reports import notification_text
    from lib.delivery import split_message
    assets=[]
    for i in range(14):
        assets.append(dict(symbol=f'S{i:02}',role='stock',status='ok',price=10,change_1d=1,
                           changes=[],is_held=i==13, strategies={'stage2_us':dict(
                               status='ok',is_signal=True,near=False,score=100-i,passed=8,
                               previous={},metrics={})}))
    invalid=copy.deepcopy(assets[0]);invalid.update(symbol='INVALID')
    invalid['strategies']['stage2_us']['status']='failed'
    near=copy.deepcopy(assets[0]);near.update(symbol='NEAR')
    near['strategies']['stage2_us'].update(is_signal=False,near=True)
    benchmark=copy.deepcopy(assets[0]);benchmark.update(symbol='BENCH',role='benchmark')
    doc=dict(target_date='2026-10-20',scope='owner',assets=assets+[invalid,near,benchmark],
             missing=0,pulse=dict(regime=None,score=None,indices={},distribution_days={},
                                 breadth=dict(stage2_count=0,analyzed=0)),url='https://example.com/')
    for mode in ('compact','standard'):
        body=notification_text(doc,mode)
        assert '符合 14只｜展示 10只｜省略 4只' in body
        assert 'S09｜' in body and 'S10｜' not in body and 'S13｜' not in body
        assert 'INVALID｜' not in body and 'NEAR｜' not in body and 'BENCH｜' not in body
        assert body.index('S00｜') < body.index('S01｜')
        assert '旧批次未计算' in body and '今日没有符合' not in body  # missing strategy data
        assert 'Checklist' not in body and '全部每日行情' not in body
        parts=split_message(body)
        assert ''.join(parts)==body and all(len(p)<=3000 for p in parts)
    # Tie: more conditions first, then stable symbol order; holding does not dominate.
    assets[1]['strategies']['stage2_us'].update(score=100,passed=9)
    body=notification_text(doc)
    assert body.index('S01｜') < body.index('S00｜')
    doc['config']={'strategies':['checklist_us']}
    body=notification_text(doc)
    assert 'Checklist' in body and 'Stage 2 趋势｜Top' not in body


def test_frozen_pipeline_results_and_digest_no_recalculation(database, monkeypatch):
    from lib import db, digest
    from tests.fixtures import seed_watchlist, update
    from lib.daily_reports import load_document
    seed_watchlist();run=update()
    with db.get_db() as conn:
        document=load_document(conn,run)
        stock=next(a for a in document['assets'] if a['symbol']=='AAA')
        assert stock['volume_price']['rule_version']=='volume-price-v1'
        assert document['pulse']['indices']['SPY']['volume_price']['parameter_id']==stock['volume_price']['parameter_id']
    def forbidden(*a,**kw):raise AssertionError('digest recalculated volume-price')
    monkeypatch.setattr('lib.volume_price.analyze',forbidden)
    config=dict(version=1,profile='owner',symbols=['AAA'],channel='trading',mode='compact')
    with digest.readonly() as conn:
        _,body,new=digest.preview(conn,config,'2026-10-20')
        assert new['assets'][0]['volume_price']==stock['volume_price']
        assert '量价' in body


def test_optional_strategy_configuration(database, tmp_path):
    from lib import digest
    from tests.fixtures import seed_watchlist
    seed_watchlist()
    base=dict(version=1,profile='owner',symbols=['AAA'],channel='trading',mode='compact')
    path=tmp_path/'digest.json'
    for selected in (['checklist_us'], ['stage2_us','checklist_us']):
        path.write_text(json.dumps(dict(base,strategies=selected)))
        with digest.readonly() as conn:
            assert digest.load_config(path,conn)['strategies']==selected
    for selected in ([], ['unknown'], ['stage2_us','stage2_us'], 'stage2_us', [1], [None]):
        path.write_text(json.dumps(dict(base,strategies=selected)))
        with digest.readonly() as conn,pytest.raises(ValueError):digest.load_config(path,conn)
