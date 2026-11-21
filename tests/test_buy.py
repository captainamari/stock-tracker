import json
import numpy as np
import pandas as pd
import pytest
from lib.buy import analyze, load_parameters
from lib.volume_price import session_context


def bars(target='2026-10-20'):
    dates, early = session_context(target, 100)
    data = pd.DataFrame(dict(Open=100., High=102., Low=98., Close=100., Volume=100.), index=pd.to_datetime(dates))
    full = [d for d in dates[:-1] if d not in early]
    data.loc[pd.to_datetime(full[-20:]), 'Volume'] = 80.
    data.loc[pd.Timestamp(target), ['Open','High','Low','Close','Volume']] = [100., 104., 99., 103., 240.]
    return data


def test_exact_volume_and_quiet_boundaries_no_lookahead():
    data = bars()
    r = analyze(data, '2026-10-20')
    assert r['status'] == 'ok' and r['is_buy']
    assert r['conditions'] == dict(C1=True,C2=True,C3=True)
    assert r['buy_volume_multiple'] == 3 and r['quiet_volume_ratio'] == .8
    assert r['reference_price'] == 103 and r['parameters']['sideways_sessions'] == 30
    future = data.iloc[[-1]].copy(); future.index = pd.to_datetime(['2026-10-21']); future.Volume = 1e9
    assert analyze(pd.concat([data,future]), '2026-10-20') == r
    json.dumps(r, allow_nan=False)


@pytest.mark.parametrize('column,value,condition', [('Volume',239.9,'C2'),('Open',103.,'C3'),('Close',100.,'C3')])
def test_trigger_requires_all_conditions(column,value,condition):
    data=bars();data.loc[data.index[-1],column]=value
    r=analyze(data,'2026-10-20')
    assert r['status']=='ok' and not r['is_buy'] and not r['conditions'][condition]
    assert r['in_buy_pool'] and r['reference_price'] is None


def test_thirty_day_range_and_low_volume_are_both_required():
    boundary=bars();boundary.loc[boundary.index[:-1],['Low','High']]=[100.,110.]
    assert analyze(boundary,'2026-10-20')['conditions']['C1']
    data=bars();data.loc[data.index[-30],'High']=120
    r=analyze(data,'2026-10-20')
    assert not r['conditions']['C1'] and not r['is_buy']
    data=bars();data.loc[data.index[-10],'Volume']=100
    assert not analyze(data,'2026-10-20')['conditions']['C1']


@pytest.mark.parametrize('bad',[0,-1,np.nan,np.inf])
def test_invalid_volume_is_unknown_not_a_negative_signal(bad):
    data=bars();data.loc[data.index[-2],'Volume']=bad
    r=analyze(data,'2026-10-20')
    assert r['status']=='insufficient_data' and r['buy_score'] is None
    assert r['conditions']['C1'] is None


def test_missing_session_invalid_ohlc_short_history_and_half_day():
    data=bars()
    assert analyze(data.drop(data.index[-3]),'2026-10-20')['status']=='insufficient_data'
    assert analyze(data.tail(30),'2026-10-20')['status']=='insufficient_data'
    data.loc[data.index[-1],'Low']=105
    assert analyze(data,'2026-10-20')['status']=='insufficient_data'
    assert analyze(bars('2026-11-27'),'2026-11-27')['reason']=='early_close'
    data=bars('2026-11-30');data.loc[pd.Timestamp('2026-11-27'),'Volume']=1
    assert analyze(data,'2026-11-30')['buy_volume_multiple']==3


def test_buy_is_independent_of_252_session_gate():
    from lib.strategy_service import evaluate_asset
    result=evaluate_asset(dict(symbol='AAA',status='ok'),bars().tail(60),None,{},'2026-10-20')
    assert result['stage2_us']['status']=='insufficient_data'
    assert result['buy_us']['status']=='ok' and result['buy_us']['is_signal']


def test_parameters_validate_and_fingerprint(tmp_path):
    p=load_parameters();p['sideways_sessions']=20
    assert analyze(bars(),'2026-10-20',p)['parameter_id'] != analyze(bars(),'2026-10-20')['parameter_id']
    p['min_volume_multiple']=float('nan');path=tmp_path/'bad.json';path.write_text(json.dumps(p))
    with pytest.raises(ValueError):load_parameters(path)


def test_publication_search_and_volume_display(client):
    from tests.fixtures import seed_watchlist, update, bars as standard_bars
    seed_watchlist()
    def provider(symbol,start,target):
        return bars(target) if symbol=='AAA' else standard_bars(symbol,start,target)
    batch=update(provider)
    for search in ['aaa','AaA','AAA','  aaa  ']:
        data=client.get('/api/assets',params={'batch':batch,'search':search}).json()
        assert data['total']==1 and data['items'][0]['symbol']=='AAA'
        assert data['items'][0]['strategies']['buy_us']['is_signal']
        assert data['items'][0]['volume_view']['summary']
    filtered=client.get('/api/assets',params={'batch':batch,'strategy':'buy_us','match':'matched'}).json()
    assert filtered['total']==1 and filtered['counts']['buy_us']==1
    detail=client.get('/ticker/aaa',params={'batch':batch,'lang':'zh'})
    assert detail.status_code==200 and '本批次 BUY 参数' in detail.text and '量价关系' in detail.text
    page=client.get('/',params={'batch':batch,'lang':'zh'})
    assert page.status_code==200 and '今日派发' in page.text and '涨跌日均量比' in page.text


def test_unknown_old_batch_and_buy_notification(client):
    from tests.fixtures import seed_watchlist, update
    from lib import db
    from lib.daily_reports import build_document, notification_text
    from lib.volume_display import describe
    seed_watchlist();batch=update()
    with db.get_db() as conn:
        pulse=json.loads(conn.execute('SELECT pulse FROM publications WHERE batch_id=?',(batch,)).fetchone()[0])
        document=build_document(conn,batch,'2026-10-20',pulse,'all')
        assert 'BUY｜Top 10' in notification_text(document)
        conn.execute("DELETE FROM daily_results WHERE run_id=? AND strategy_id='buy_us'",(batch,))
    response=client.get('/api/assets',params={'batch':batch,'symbols':'AAA'}).json()
    assert response['evaluated_counts']['buy_us']==0
    assert describe(None)['summary'][0][1]=='该批次未计算量价'


def test_recalculate_pins_inputs_preserves_history_and_sends_nothing(database,monkeypatch):
    from tests.fixtures import seed_watchlist, update
    from lib import db
    from lib.recalculate import latest
    from lib.queries import dashboard_data, report_data
    seed_watchlist();first=update();before=report_data(first)['body']
    with db.get_db() as conn:
        revisions=conn.execute('SELECT count(*) FROM price_revisions').fetchone()[0]
        deliveries=conn.execute('SELECT count(*) FROM deliveries').fetchone()[0]
    def forbidden(*args,**kwargs):raise AssertionError('No network permitted')
    monkeypatch.setattr('lib.prices.download',forbidden)
    result=latest()
    assert result['source_batch']==first and result['batch_id']!=first
    assert dashboard_data()['batch_id']==result['batch_id']
    assert report_data(first)['body']==before
    with db.get_db() as conn:
        assert conn.execute('SELECT count(*) FROM price_revisions').fetchone()[0]==revisions
        assert conn.execute('SELECT count(*) FROM deliveries').fetchone()[0]==deliveries
        for key in ('symbol','input_revision','actual_date'):
            old=[r[0] for r in conn.execute(f'SELECT {key} FROM run_assets WHERE run_id=? ORDER BY symbol',(first,))]
            new=[r[0] for r in conn.execute(f'SELECT {key} FROM run_assets WHERE run_id=? ORDER BY symbol',(result['batch_id'],))]
            assert old==new


def test_recalculate_failure_keeps_publication_and_active_work_is_rejected(database,monkeypatch):
    from tests.fixtures import seed_watchlist, update, NOW
    from lib.recalculate import latest
    from lib.queries import dashboard_data
    from lib.jobs import enqueue
    seed_watchlist();batch=update()
    def fail(*args): raise RuntimeError('calculation failed')
    monkeypatch.setattr('lib.strategy_service.calculate_run',fail)
    with pytest.raises(RuntimeError):latest()
    assert dashboard_data()['batch_id']==batch
    enqueue('manual',now=NOW)
    with pytest.raises(ValueError,match='active'):latest()
