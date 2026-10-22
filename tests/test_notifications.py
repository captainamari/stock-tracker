from datetime import datetime,timezone
import json
import time
import httpx
import pytest
from lib import db,delivery
from lib.schedule import save_schedule,tick,get_schedule
from tests.fixtures import seed_watchlist,update


def enable():
    save_schedule(dict(update_time='04:00',notify_time='06:00',channel='trading',enabled=True))


def test_due_time_dst_holiday_and_missing_report(database):
    enable()
    # NYC 05:59 EDT: update due, notify not due.
    assert [x[0] for x in tick(datetime(2026,10,21,9,59,tzinfo=timezone.utc))]==['update']
    assert [x[0] for x in tick(datetime(2026,10,21,10,tzinfo=timezone.utc))]==['notify']
    assert tick(datetime(2026,10,21,11,tzinfo=timezone.utc))==[]
    assert tick(datetime(2026,12,25,12,tzinfo=timezone.utc))==[]
    with db.get_db() as conn:
        report=dict(conn.execute("SELECT * FROM report_snapshots WHERE kind='missing'").fetchone())
    assert report['target_date']=='2026-10-20' and 'Delayed or missing' in report['body']
    assert not any(x[0]=='notify' for x in tick(datetime(2026,11,2,10,59,tzinfo=timezone.utc)))
    assert any(x[0]=='notify' for x in tick(datetime(2026,11,2,11,tzinfo=timezone.utc)))


def test_schedule_save_does_not_send_and_no_late_resend(admin):
    payload=dict(update_time='04:00',notify_time='06:00',channel='trading',enabled=True)
    assert admin.put('/api/settings',json=payload).status_code==200
    assert delivery.list_deliveries()==[]
    tick(datetime(2026,10,21,10,tzinfo=timezone.utc))
    queued=delivery.list_deliveries()[0]['delivery_id']
    seed_watchlist()
    # Scheduler has already queued the same update scope.
    update()
    tick(datetime(2026,10,21,12,tzinfo=timezone.utc))
    assert len(delivery.list_deliveries())==1
    with db.get_db() as conn:
        snapshot=conn.execute('SELECT r.kind FROM deliveries d JOIN report_snapshots r USING(report_id) WHERE d.delivery_id=?',(queued,)).fetchone()[0]
    assert snapshot=='missing'


def test_hub_adapter_receipts_and_no_blind_retry(database,monkeypatch):
    monkeypatch.delenv('NOTIFICATION_API_URL',raising=False)
    monkeypatch.delenv('NOTIFICATION_API_TOKEN',raising=False)
    assert get_schedule()['channel']=='trading' and get_schedule()['enabled'] is False
    calls=[]
    def handler(request):
        calls.append(request)
        assert str(request.url)=='https://notify.watchpoint.space/api/v1/notify'
        assert request.headers['authorization']=='Bearer synthetic-contract-token'
        payload=json.loads(request.content)
        assert set(payload)=={'title','message','channel','level','source','metadata'}
        assert payload['channel']=='trading'
        return httpx.Response(200,json=dict(request_id='receipt',status='sent',channel='trading',delivered_to=['synthetic'],skipped=[],failed={}))
    identifier=delivery.queue_test()
    client=delivery.HubClient(httpx.Client(transport=httpx.MockTransport(handler)))
    assert delivery.run_once(client)==identifier
    assert delivery.list_deliveries()[0]['status']=='blocked' and calls==[]
    monkeypatch.setenv('NOTIFICATION_API_TOKEN','synthetic-contract-token')
    delivery.retry(identifier)
    assert delivery.run_once(client)==identifier
    assert delivery.run_once(client) is None
    assert len(calls)==1 and delivery.list_deliveries()[0]['status']=='sent'
    def timeout(request):
        raise httpx.ReadTimeout('isolated fault')
    identifier=delivery.queue_test()
    delivery.run_once(delivery.HubClient(httpx.Client(transport=httpx.MockTransport(timeout))))
    assert next(r for r in delivery.list_deliveries() if r['delivery_id']==identifier)['status']=='unknown'
    with pytest.raises(ValueError):
        delivery.retry(identifier)
    assert delivery.run_once(client) is None
    delivery.resolve(identifier)


def test_long_message_partial_retry_and_crash(database):
    body='synthetic 日报\n'*1000
    with db.get_db() as conn:
        conn.execute("INSERT INTO report_snapshots VALUES ('long',NULL,'2026-10-20','test',?,'2026-10-21',0)",(body,))
        identifier=delivery.queue_report(conn,'long','2026-10-20','trading','isolated-long')
        assert delivery.queue_report(conn,'long','2026-10-20','trading','isolated-long')==identifier
    calls=[]
    class Client:
        def send(self,item,part,total):
            calls.append(part['part'])
            if len(calls)==2:
                return 'retryable',None,'connection_not_established'
            return 'sent',{'request_id':'synthetic'},None
    client=Client()
    delivery.run_once(client)
    assert calls==[1,2]
    delivery.retry(identifier)
    delivery.run_once(client)
    assert calls.count(1)==1 and calls.count(2)==2
    with db.get_db() as conn:
        assert ''.join(r[0] for r in conn.execute('SELECT body FROM delivery_parts WHERE delivery_id=? ORDER BY part',(identifier,)))==body
    other=delivery.queue_test()
    item=delivery.claim()
    assert item['delivery_id']==other
    with db.get_db() as conn:
        conn.execute("UPDATE delivery_parts SET status='sending' WHERE delivery_id=?",(other,))
        conn.execute('UPDATE deliveries SET lease_until=? WHERE delivery_id=?',(time.time()-1,other))
    assert delivery.claim() is None
    assert next(r for r in delivery.list_deliveries() if r['delivery_id']==other)['status']=='unknown'


def test_partial_delivery_never_retries(database):
    identifier=delivery.queue_test()
    class Partial:
        def send(self,*args):
            return 'partial',{'request_id':'test','delivered_to':['one'],'failed':{'two':'failure'}},'partial'
    delivery.run_once(Partial())
    assert delivery.list_deliveries()[0]['status']=='partial'
    with pytest.raises(ValueError):
        delivery.retry(identifier)
    assert delivery.run_once(Partial()) is None


def test_malformed_success_receipts_are_unknown(monkeypatch):
    monkeypatch.setenv('NOTIFICATION_API_URL','http://isolated.invalid')
    monkeypatch.setenv('NOTIFICATION_API_TOKEN','synthetic-contract-token')
    item=dict(target_date='2026-10-20',channel='trading',report_id='isolated')
    part=dict(part=1,body='SYNTHETIC')
    for payload in ([],None,'sent',{'status':'sent','request_id':'','channel':'trading','delivered_to':['telegram']},
                    {'status':'sent','request_id':'receipt','channel':'trading','delivered_to':[None]}):
        with httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(200,json=payload))) as client:
            assert delivery.HubClient(client).send(item,part,1)[0]=='unknown'
