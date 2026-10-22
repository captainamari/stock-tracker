import json
from types import SimpleNamespace
import pytest
from lib import db
from lib.queries import dashboard_data, ticker_data, report_data
from lib.prices import normalize, BASIS
from tests.fixtures import bars,seed_watchlist,update


def test_missing_benchmark_keeps_all_eight_conditions():
    from scripts.stage2_monitor import check_stage2_conditions
    data = bars('AAA')
    r = check_stage2_conditions(SimpleNamespace(symbol='AAA',name='synthetic',sector=''),loader=lambda ticker,min_rows=0: data if ticker=='AAA' else None)
    assert r['conditions']['C8'] is None
    assert r['total']==8 and not r['is_stage2']
    assert r['status']=='insufficient_data'


def test_twenty_elapsed_sessions_and_benchmark_date_alignment():
    from scripts.stage2_monitor import check_stage2_conditions
    data=bars('AAA').tail(252).copy()
    data['Close']=100.
    data.iloc[232,data.columns.get_loc('Close')]=200.
    data.iloc[233:,data.columns.get_loc('Close')]=99.
    spy=bars('SPY')
    info=SimpleNamespace(symbol='AAA',name='SYNTHETIC',sector='')
    result=check_stage2_conditions(info,loader=lambda symbol,min_rows=0:data if symbol=='AAA' else spy)
    # 20 elapsed sessions rises, while the former 19-session boundary falls.
    assert result['conditions']['C3']
    missing=spy.drop(data.index[-50])
    result=check_stage2_conditions(info,loader=lambda symbol,min_rows=0:data if symbol=='AAA' else missing)
    assert result['conditions']['C8'] is None and result['total']==8
    assert result['status']=='insufficient_data' and not result['is_stage2']


def test_no_cross_run_cache(database):
    from scripts.stage2_monitor import fetch_stock_data
    db.upsert_prices('AAA',[dict(date='2026-10-19',open=2,high=2,low=2,close=2,volume=100)])
    assert fetch_stock_data('AAA',min_rows=1)['Close'].iloc[-1]==2
    db.upsert_prices('AAA',[dict(date='2026-10-19',open=3,high=3,low=3,close=3,volume=100)])
    assert fetch_stock_data('AAA',min_rows=1)['Close'].iloc[-1]==3


def test_real_call_chain_and_frozen_revisions(database):
    seed_watchlist()
    first = update()
    data = dashboard_data()
    assert data['batch_id']==first
    aaa = ticker_data('AAA')
    assert aaa['strategies']['stage2_us']['status']=='ok'
    assert aaa['strategies']['stage2_us']['is_signal'] is True
    assert aaa['asset']['price']==aaa['prices'][-1]['close']
    assert aaa['strategies']['technical']['status']=='ok'
    before = report_data(first)['body']
    old_close = aaa['prices'][-1]['close']
    def revised(symbol,start,target):
        data=bars(symbol,start,target)
        data[['Open','High','Low','Close']] *= .9
        return data
    second = update(revised)
    assert second!=first
    assert ticker_data('AAA')['prices'][-1]['close'] != old_close
    assert ticker_data('AAA',first)['prices'][-1]['close'] == old_close
    assert report_data(first)['body']==before
    assert 'Market date 2026-10-20' in before
    with db.get_db() as conn:
        assert conn.execute('SELECT COUNT(*) FROM daily_results WHERE run_id=?',(second,)).fetchone()[0]==25
        assert conn.execute('SELECT COUNT(DISTINCT basis) FROM price_revisions').fetchone()[0]==1


def test_failure_is_not_exit_and_zero_candidates_is_zero(database,monkeypatch):
    from lib import strategy_service
    seed_watchlist()
    # Controlled conditions exercise the actual publish/state chain, not production data.
    def candidate(symbol, info, frame, state):
        return dict(conditions={f'C{i}':True for i in range(1,7)},is_vcp=True)
    monkeypatch.setattr(strategy_service,'analyze_vcp',candidate)
    first = update()
    with db.get_db() as conn:
        entry = dict(conn.execute("SELECT * FROM candidate_states WHERE symbol='AAA' AND strategy_id='contraction_us'").fetchone())
    update()
    with db.get_db() as conn:
        again = dict(conn.execute("SELECT * FROM candidate_states WHERE symbol='AAA' AND strategy_id='contraction_us'").fetchone())
    assert again['entry_date']==entry['entry_date'] and again['entry_price']==entry['entry_price']
    def fail(*args):
        raise RuntimeError('isolated fault injection')
    monkeypatch.setattr(strategy_service,'analyze_vcp',fail)
    update()
    with db.get_db() as conn:
        assert conn.execute("SELECT active FROM candidate_states WHERE symbol='AAA' AND strategy_id='contraction_us'").fetchone()[0]==1
    monkeypatch.setattr(strategy_service,'analyze_vcp',lambda *args:dict(conditions={f'C{i}':False for i in range(1,7)},is_vcp=False))
    last=update()
    assert dashboard_data()['counts']['contraction_us']==0
    assert dashboard_data(first)['counts']['contraction_us']==1
    with db.get_db() as conn:
        assert conn.execute("SELECT active FROM candidate_states WHERE symbol='AAA' AND strategy_id='contraction_us'").fetchone()[0]==0
        assert conn.execute("SELECT COUNT(*) FROM candidate_changes WHERE batch_id=? AND strategy_id='contraction_us' AND change_type='exit'",(last,)).fetchone()[0]==1


def test_source_failure_short_history_and_recompute_without_new_rows(database):
    seed_watchlist(('AAA','SHORT','FAIL'))
    def provider(symbol,start,target):
        if symbol=='FAIL':
            raise RuntimeError('isolated provider failure')
        return bars(symbol,start,target,short=symbol=='SHORT')
    update(provider)
    short=ticker_data('SHORT')
    assert len(short['prices'])==25 and short['asset']['price']>0
    assert short['strategies']['stage2_us']['status']=='insufficient_data'
    assert ticker_data('FAIL')['strategies']['stage2_us']['status']=='failed'
    with db.get_db() as conn:
        before=conn.execute('SELECT COUNT(*) FROM price_revisions').fetchone()[0]
    update(provider)
    with db.get_db() as conn:
        after=conn.execute('SELECT COUNT(*) FROM price_revisions').fetchone()[0]
    # Fixture returns start-dependent values, so use constant full-history provider
    # below to verify a true no-new-row retry.
    constant=lambda symbol,start,target: bars(symbol,'2024-08-12',target)
    update(constant)
    with db.get_db() as conn:
        before=conn.execute('SELECT COUNT(*) FROM price_revisions').fetchone()[0]
    run=update(constant)
    with db.get_db() as conn:
        assert conn.execute('SELECT COUNT(*) FROM price_revisions').fetchone()[0]==before
        assert conn.execute("SELECT COUNT(*) FROM daily_results WHERE run_id=? AND status='ok'",(run,)).fetchone()[0]>0


def test_unfinished_bar_missing_volume_and_ohlc_validation():
    frame=bars('AAA',target='2026-10-21').tail(3)
    frame.loc[frame.index[0],'Volume']=float('nan')
    values=normalize(frame,'2026-10-20')
    assert len(values)==2
    assert values[0]['quality']=='missing_volume' and values[0]['volume'] is None
    assert values[-1]['date']=='2026-10-20'
    frame.loc[frame.index[1],'High']=1
    assert normalize(frame,'2026-10-20')[-1]['quality']=='invalid_ohlc'


def test_price_basis_never_falls_back(monkeypatch):
    import yfinance
    from lib.prices import download
    calls=[]
    class Broken:
        def history(self,**kw):
            calls.append(kw)
            raise RuntimeError('failure')
    monkeypatch.setattr(yfinance,'Ticker',lambda _:Broken())
    monkeypatch.setattr('lib.prices.time.sleep',lambda _:None)
    monkeypatch.setattr('lib.provider_guard.before_call',lambda:None)
    with pytest.raises(RuntimeError):
        download('AAA','2025-01-01','2026-10-20')
    assert len(calls)==3 and all(c['auto_adjust'] is True for c in calls)


def test_leaving_stage2_pool_clears_vcp_via_real_chain(database,monkeypatch):
    from lib import strategy_service
    seed_watchlist()
    monkeypatch.setattr(strategy_service,'analyze_vcp',lambda *args:dict(conditions={f'C{i}':True for i in range(1,7)},is_vcp=True))
    first=update()
    assert dashboard_data()['counts']['contraction_us']==1
    def falling(symbol,start,target):
        frame=bars(symbol,start,target)
        if symbol=='AAA':
            close=250-frame['Close']*.6
            frame['Close']=close
            frame['Open']=close-.2
            frame['High']=close+1
            frame['Low']=close-1
        return frame
    last=update(falling)
    assert ticker_data('AAA')['strategies']['stage2_us']['status']=='ok'
    assert dashboard_data()['counts']['stage2_us']==0
    assert dashboard_data()['counts']['contraction_us']==0
    with db.get_db() as conn:
        assert conn.execute("SELECT active FROM candidate_states WHERE symbol='AAA' AND strategy_id='contraction_us'").fetchone()[0]==0
        assert conn.execute("SELECT COUNT(*) FROM candidate_changes WHERE batch_id=? AND strategy_id='contraction_us' AND change_type='exit'",(last,)).fetchone()[0]==1
    assert dashboard_data(first)['counts']['contraction_us']==1


def test_market_date_cannot_move_backwards(database):
    from datetime import datetime,timezone
    seed_watchlist()
    first=update()
    with pytest.raises(ValueError,match='older market date'):
        update(now=datetime(2026,10,20,8,tzinfo=timezone.utc))
    assert dashboard_data()['batch_id']==first


def test_full_csv_and_backup_preserve_published_inputs(client,tmp_path):
    from lib.backup import backup,restore
    import csv,io,sqlite3
    seed_watchlist()
    run=update()
    data=ticker_data('AAA')
    csv_rows=list(csv.DictReader(io.StringIO(client.get(f'/api/ticker/AAA/prices.csv?batch={run}').text)))
    assert len(csv_rows)==len(data['prices'])>500
    assert csv_rows[0]['date']==data['prices'][0]['date']
    assert float(csv_rows[-1]['close'])==data['asset']['price']
    saved=backup(tmp_path/'snapshot.db')
    restored=restore(saved,tmp_path/'restored.db')
    with sqlite3.connect(restored) as conn:
        assert conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert conn.execute('SELECT batch_id FROM current_publication').fetchone()[0]==run
        assert conn.execute('SELECT COUNT(*) FROM daily_results').fetchone()[0]==25
