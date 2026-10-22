import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from lib import db, delivery
from lib.daily_reports import build_document, load_document, notification_preview, notification_text
from lib.interests import update as labels
from lib.listing import paginate, select
from lib.migrations import migrate
from tests.fixtures import seed_watchlist, update


def test_upgrade_labels_once_and_preserves_data(tmp_path):
    path = tmp_path / 'upgrade.db'
    db.init_db(path)
    with db.get_db(path) as conn:
        conn.execute('CREATE TABLE schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)')
        for file in sorted(Path('migrations').glob('*.sql')):
            if file.name.startswith('007'):
                break
            for statement in file.read_text(encoding='utf-8').split(';'):
                if statement.strip():
                    conn.execute(statement)
            conn.execute('INSERT INTO schema_migrations VALUES (?,?)', (file.name, 'test'))
        conn.execute("INSERT INTO watchlist(symbol,name,is_personal,is_public,enabled) VALUES ('MY','Mine',1,0,0),('INDEX','Index',0,1,1)")
        conn.execute("INSERT INTO stock_prices(symbol,date,close) VALUES ('MY','2020-01-02',123)")
    migrate(path)
    with db.get_db(path) as conn:
        assert tuple(conn.execute("SELECT is_followed,is_held,is_public,enabled FROM watchlist WHERE symbol='MY'").fetchone()) == (1,0,0,0)
        assert tuple(conn.execute("SELECT is_followed,is_held FROM watchlist WHERE symbol='INDEX'").fetchone()) == (0,0)
        conn.execute("UPDATE watchlist SET is_followed=0 WHERE symbol='MY'")
    migrate(path)
    with db.get_db(path) as conn:
        assert conn.execute("SELECT is_followed FROM watchlist WHERE symbol='MY'").fetchone()[0] == 0
        assert conn.execute('SELECT close FROM stock_prices').fetchone()[0] == 123


def test_bulk_labels_atomic_private_and_independent(admin):
    seed_watchlist(('AAA','BBB'))
    with db.get_db() as conn:
        conn.execute("UPDATE watchlist SET is_personal=0,is_public=0 WHERE symbol='AAA'")
    response=admin.patch('/api/interests',json={'symbols':['AAA','BBB','AAA'],'is_followed':True})
    assert response.status_code==200
    assert admin.patch('/api/interests',json={'symbols':['AAA','UNKNOWN'],'is_held':True}).status_code==422
    labels(['AAA'],held=True,followed=False)
    with db.get_db() as conn:
        assert tuple(conn.execute("SELECT is_followed,is_held,is_personal,is_public,enabled FROM watchlist WHERE symbol='AAA'").fetchone())==(0,1,1,0,1)
        assert conn.execute("SELECT is_held FROM watchlist WHERE symbol='BBB'").fetchone()[0]==0
    labels(['AAA'],held=False)
    with db.get_db() as conn:
        assert conn.execute("SELECT enabled FROM watchlist WHERE symbol='AAA'").fetchone()[0]==1
    csrf=admin.headers.pop('x-csrf-token')
    assert admin.patch('/api/interests',json={'symbols':['BBB'],'is_followed':False}).status_code==403
    admin.headers['x-csrf-token']=csrf
    admin.post('/api/auth/logout')
    assert admin.patch('/api/interests',json={'symbols':['BBB'],'is_followed':False}).status_code==401
    assert admin.get('/api/assets?scope=following').status_code==401
    assert 'is_followed' not in admin.get('/api/ticker/BBB').text


def test_filter_whole_list_then_paginate_with_stable_ties(admin):
    seed_watchlist(tuple(f'S{i:03}' for i in range(65)))
    labels([f'S{i:03}' for i in range(10,65)],followed=True)
    labels(['S064'],held=True)
    first=admin.get('/api/assets?scope=following').json()
    second=admin.get('/api/assets?scope=following&page=2').json()
    assert first['total']==55 and first['pages']==3
    assert first['items'][0]['symbol']=='S010' and second['items'][0]['symbol']=='S030'
    searched=admin.get('/api/assets?scope=personal&search=s064&page=99').json()
    assert searched['total']==1 and searched['page']==1 and searched['items'][0]['symbol']=='S064'
    assert admin.get('/watchlist?scope=held').status_code==200
    assert admin.get('/admin?scope=following&page=2').status_code==200
    assert admin.get('/watchlist?page=bad').status_code==422
    rows=[dict(symbol=s,name='',price=5,role='stock',strategies={}) for s in ['ZZ','AA','BB']]
    assert [r['symbol'] for r in select(rows,sort='price')]==['AA','BB','ZZ']
    assert paginate([],99)['page']==1 and paginate([],99)['total']==0


def test_state_filter_without_selected_strategy_matches_any_strategy():
    rows=[dict(symbol=s,name='',role='stock',strategies=r) for s,r in [
        ('MATCH',{'stage2_us':{'status':'ok','is_signal':True,'passed':8}}),
        ('NEAR',{'checklist_us':{'status':'ok','is_signal':False,'passed':5}}),
        ('UNKNOWN',{'stage2_us':{'status':'failed','is_signal':None,'passed':0}})]]
    assert [a['symbol'] for a in select(rows,match='matched')]==['MATCH']
    assert [a['symbol'] for a in select(rows,match='near')]==['NEAR']
    assert not select(rows,strategy='stage2_us',match='near')


def test_frozen_private_reports_preview_no_io_and_public_separation(admin, monkeypatch):
    seed_watchlist(('AAA','SECRET','OTHER'))
    labels(['AAA','SECRET'],followed=True)
    labels(['SECRET'],held=True)
    with db.get_db() as conn:
        conn.execute("UPDATE watchlist SET is_public=0 WHERE symbol='SECRET'")
    run=update()
    with db.get_db() as conn:
        original=load_document(conn,run+'-personal')
        public=load_document(conn,run)
        assert {a['symbol'] for a in original['assets']}=={'AAA','SECRET'}
        assert 'SECRET' not in json.dumps(public)
        assert all('is_held' not in a and 'is_followed' not in a for a in public['assets'])
        assert original['assets'][0]['symbol']=='SECRET'
        rendered=notification_text(original)
        assert 'SECRET' in rendered and 'OTHER' not in rendered
        assert 'MA50' in rendered and '▓' in rendered and '/reports/'+run+'-personal' in rendered
    labels(['SECRET'],held=False,followed=False)
    labels(['OTHER'],held=True)
    def prohibited(*args,**kwargs):
        raise AssertionError('Preview or GET caused I/O/computation/delivery')
    monkeypatch.setattr('lib.prices.download',prohibited)
    monkeypatch.setattr('lib.strategy_service.calculate_run',prohibited)
    monkeypatch.setattr('lib.delivery.queue_report',prohibited)
    monkeypatch.setattr('lib.market_calendar.completed_session',lambda *args:'2026-10-20')
    result=admin.get('/api/notifications/preview?scope=personal').json()
    assert result['report_id']==run+'-personal' and 'SECRET' in ''.join(result['parts'])
    for path in [f'/reports/{run}-personal',f'/reports/{run}-following',f'/reports/{run}-held',f'/reports/{run}','/daily','/admin']:
        response=admin.get(path)
        assert response.status_code==200,(path,response.text[:100])
    with db.get_db() as conn:
        assert load_document(conn,run+'-personal')==original
        assert conn.execute('SELECT COUNT(*) FROM deliveries').fetchone()[0]==0
    admin.post('/api/auth/logout')
    for path in [f'/reports/{run}-personal',f'/reports/{run}-following',f'/reports/{run}-held']:
        assert admin.get(path).status_code==404
    assert 'SECRET' not in admin.get('/daily').text
    assert admin.get('/api/notifications/preview').status_code==401


def test_private_schedule_exact_date_and_frozen_parts(database):
    from lib.schedule import save_schedule
    seed_watchlist(('AAA','BBB'))
    labels(['AAA'],held=True)
    run=update()
    save_schedule(dict(update_time='04:00',notify_time='06:00',channel='trading',enabled=True,report_scope='held',report_mode='compact'))
    with db.get_db() as conn:
        ident=delivery.queue_daily(conn,'2026-10-20','2026-10-21','trading')
        assert delivery.queue_daily(conn,'2026-10-20','2026-10-21','trading')==ident
        assert conn.execute('SELECT report_id FROM deliveries').fetchone()[0]==run+'-held'
        parts=''.join(r[0] for r in conn.execute('SELECT body FROM delivery_parts ORDER BY part'))
        assert 'AAA' in parts and 'BBB' not in parts and 'All daily prices' not in parts
        missing,body=notification_preview(conn,'2026-10-21','personal')
        assert missing is None and '2026-10-21' in body and 'AAA' not in body
    labels(['AAA'],held=False)
    with db.get_db() as conn:
        assert ''.join(r[0] for r in conn.execute('SELECT body FROM delivery_parts ORDER BY part'))==parts


def test_comparison_requires_adjacent_session_and_successful_evaluation(database):
    seed_watchlist()
    labels(['AAA'],followed=True)
    before=update(now=datetime(2026,10,20,12,tzinfo=timezone.utc))  # October 19 session
    current=update()
    with db.get_db() as conn:
        document=load_document(conn,current+'-personal')
        assert document['previous_batch']==before
        assert document['assets'][0]['strategies']['stage2_us']['previous'] is not None
        row=conn.execute("SELECT payload FROM daily_results WHERE run_id=? AND symbol='AAA' AND strategy_id='stage2_us'",(before,)).fetchone()
        broken=json.loads(row[0]); broken.update(status='failed',is_signal=None)
        conn.execute("UPDATE daily_results SET payload=? WHERE run_id=? AND symbol='AAA' AND strategy_id='stage2_us'",(json.dumps(broken),before))
        rebuilt=build_document(conn,current,'2026-10-20',document['pulse'],'personal')
        assert rebuilt['assets'][0]['strategies']['stage2_us']['previous'] is None
        assert not rebuilt['assets'][0]['changes']
        conn.execute("UPDATE publications SET target_date='2026-10-16' WHERE batch_id=?",(before,))
        rebuilt=build_document(conn,current,'2026-10-20',document['pulse'],'personal')
        assert rebuilt['previous_batch'] is None and not rebuilt['assets'][0]['changes']


def test_legacy_reports_and_new_scopes_without_snapshot(admin):
    seed_watchlist()
    run=update()
    with db.get_db() as conn:
        conn.execute('DELETE FROM report_documents')
        conn.execute('DELETE FROM report_snapshots WHERE public=0')
    assert admin.get('/daily?scope=personal').status_code==200
    assert '下次数据更新后' in admin.get('/daily?scope=personal').text
    assert 'class="report"' in admin.get('/reports/'+run).text


def test_paragraph_splitting_preserves_cards_and_unicode():
    body='标题\n\n'+('AAA 📊\n'+'x'*700+'\n\n')*8
    parts=delivery.split_message(body,1000)
    assert ''.join(parts)==body and all(len(p)<=1000 for p in parts)
    assert all('AAA 📊' not in p or p.count('x')==700 for p in parts)
    assert ''.join(delivery.split_message('x'*7200))=='x'*7200


def test_missing_session_sparkline_keeps_gap(database):
    from tests.fixtures import bars
    from web.deps import spark_path
    seed_watchlist()
    labels(['AAA'],followed=True)
    def missing(symbol,start,target):
        frame=bars(symbol,start,target)
        return frame.drop(frame.index[-5]) if symbol=='AAA' else frame
    run=update(missing)
    with db.get_db() as conn:
        a=load_document(conn,run+'-personal')['assets'][0]
        assert len(a['sparkline'])==20 and a['sparkline'][-5] is None
        assert spark_path(a['sparkline']).count('M')==2


def test_notification_history_pagination(admin):
    for _ in range(25):
        delivery.queue_test()
    first=admin.get('/api/notifications?page=1').json()
    second=admin.get('/api/notifications?page=2').json()
    assert first['total']==25 and len(first['items'])==20 and len(second['items'])==5
    assert not {r['delivery_id'] for r in first['items']} & {r['delivery_id'] for r in second['items']}
