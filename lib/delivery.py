"""notification-hub contract adapter and durable, conservative delivery outbox.

Pinned contract: captainamari/notification-hub@7c6ef039.
The hub has no idempotency or receipt-query endpoint. Local deduplication cannot
provide exactly-once delivery. Ambiguous requests and partial sends are held.
"""
import json
import time
import uuid
import httpx
from lib import db
from lib.settings import settings, stamp


def split_message(body,limit=3000):
    parts=[]
    while body:
        cut=min(len(body),limit)
        if cut<len(body):
            newline=body.rfind('\n',0,cut)
            if newline>limit//2:
                cut=newline+1
        parts.append(body[:cut])
        body=body[cut:]
    return parts or ['No content']


def queue_report(conn, report_id, target, channel, key=None):
    if key:
        old=conn.execute('SELECT delivery_id FROM deliveries WHERE schedule_key=?',(key,)).fetchone()
        if old:
            return old[0]
    report=conn.execute('SELECT body FROM report_snapshots WHERE report_id=?',(report_id,)).fetchone()
    delivery_id=uuid.uuid4().hex
    now=stamp()
    conn.execute('''INSERT INTO deliveries(delivery_id,report_id,target_date,channel,backend,status,created_at,updated_at,schedule_key)
        VALUES (?,?,?,?,'hub','queued',?,?,?)''',(delivery_id,report_id,target,channel,now,now,key))
    conn.executemany('INSERT INTO delivery_parts(delivery_id,part,body,status) VALUES (?,?,?,?)',
                     [(delivery_id,i+1,body,'queued') for i,body in enumerate(split_message(report[0]))])
    return delivery_id


def queue_daily(conn,target,local_date,channel):
    pub=conn.execute('SELECT batch_id FROM publications WHERE target_date=? ORDER BY published_at DESC LIMIT 1',(target,)).fetchone()
    report_id=pub[0] if pub else 'missing-'+local_date
    if not pub:
        body=f'Stock Tracker · 延迟/缺失 / Delayed or missing\n目标行情日期 / Expected market date: {target}\n没有该交易日的已发布日报；不会使用旧日报代替。\nNo published report for the target session. An older report is not substituted.\n{settings().public_url}'
        conn.execute('INSERT OR IGNORE INTO report_snapshots VALUES (?,NULL,?,?,?,?,1)',(report_id,target,'missing',body,stamp()))
    return queue_report(conn,report_id,target,channel,'daily:'+local_date)


def queue_test():
    from lib.schedule import get_schedule
    with db.get_db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        identifier='test-'+uuid.uuid4().hex
        target=stamp()[:10]
        conn.execute('INSERT INTO report_snapshots VALUES (?,NULL,?,?,?,?,0)',(identifier,target,'test','Stock Tracker · Explicit test / 明确操作的测试消息',stamp()))
        return queue_report(conn,identifier,target,get_schedule(conn)['channel'])


class HubClient:
    def __init__(self,client=None):
        self.client=client

    def send(self,delivery,part,total):
        cfg=settings()
        if not cfg.hub_url or not cfg.hub_token:
            return 'blocked',None,'hub_not_configured'
        payload=dict(title=f'Stock Tracker {delivery["target_date"]} ({part["part"]}/{total})',message=part['body'],channel=delivery['channel'],level='info',source='stock-tracker',
                     metadata={'report_id':delivery['report_id'],'part':part['part'],'parts':total})
        own=self.client is None
        client=self.client or httpx.Client(timeout=httpx.Timeout(30,connect=10),follow_redirects=False)
        try:
            response=client.post(cfg.hub_url+'/api/v1/notify',headers={'Authorization':'Bearer '+cfg.hub_token},json=payload)
            if response.status_code==429:
                return 'retryable',None,'rate_limited'
            if response.status_code in (400,401,403,404,422,503):
                return 'blocked',None,f'hub_rejected_{response.status_code}'
            if response.status_code!=200:
                return 'unknown',None,f'hub_response_{response.status_code}'
            result=response.json()
            if not isinstance(result.get('request_id'),str) or result.get('channel')!=delivery['channel'] or not isinstance(result.get('delivered_to'),list):
                return 'unknown',None,'invalid_receipt'
            if result.get('status')=='sent' and result['delivered_to'] and not result.get('failed') and not result.get('skipped'):
                return 'sent',result,None
            if result.get('status')=='partial':
                return 'partial',result,'partial_delivery_review_required'
            return 'unknown',result,'unconfirmed_receipt'
        except (httpx.ConnectError,httpx.ConnectTimeout):
            return 'retryable',None,'connection_not_established'
        except (httpx.TimeoutException,httpx.TransportError,ValueError):
            return 'unknown',None,'request_result_unknown'
        finally:
            if own:
                client.close()


def claim():
    now=time.time()
    with db.get_db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        expired=conn.execute("SELECT delivery_id FROM deliveries WHERE status='sending' AND lease_until<?",(now,)).fetchall()
        for row in expired:
            # Crash between remote delivery and local receipt cannot be retried safely.
            conn.execute("UPDATE delivery_parts SET status='unknown',error='worker_interrupted' WHERE delivery_id=? AND status='sending'",(row[0],))
            conn.execute("UPDATE deliveries SET status='unknown',updated_at=? WHERE delivery_id=?",(stamp(),row[0]))
        row=conn.execute("SELECT * FROM deliveries WHERE status IN ('queued','retryable') AND next_attempt<=? ORDER BY created_at LIMIT 1",(now,)).fetchone()
        if not row:
            return None
        owner=uuid.uuid4().hex
        conn.execute("UPDATE deliveries SET status='sending',owner=?,lease_until=?,updated_at=? WHERE delivery_id=?",(owner,now+120,stamp(),row['delivery_id']))
        return dict(conn.execute('SELECT * FROM deliveries WHERE delivery_id=?',(row['delivery_id'],)).fetchone())


def fence(conn,item):
    if not conn.execute("SELECT 1 FROM deliveries WHERE delivery_id=? AND owner=? AND status='sending' AND lease_until>?",(item['delivery_id'],item['owner'],time.time())).fetchone():
        raise RuntimeError('Delivery lease lost')


def run_once(client=None):
    item=claim()
    if not item:
        return None
    client=client or HubClient()
    with db.get_db() as conn:
        parts=[dict(r) for r in conn.execute('SELECT * FROM delivery_parts WHERE delivery_id=? ORDER BY part',(item['delivery_id'],))]
    for part in parts:
        if part['status']=='sent':
            continue
        with db.get_db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            fence(conn,item)
            conn.execute("UPDATE delivery_parts SET status='sending',attempts=attempts+1 WHERE delivery_id=? AND part=?",(item['delivery_id'],part['part']))
            conn.execute('UPDATE deliveries SET lease_until=? WHERE delivery_id=?',(time.time()+120,item['delivery_id']))
        status,receipt,error=client.send(item,part,len(parts))
        with db.get_db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            fence(conn,item)
            conn.execute('UPDATE delivery_parts SET status=?,receipt=?,error=? WHERE delivery_id=? AND part=?',
                         (status,json.dumps(receipt) if receipt else None,error,item['delivery_id'],part['part']))
            if status!='sent':
                # Safe failures get at most three automatic attempts; no request
                # with uncertain delivery is ever included in this retry path.
                delivery_status='blocked' if status=='retryable' and part['attempts']>=2 else status
                conn.execute('UPDATE deliveries SET status=?,updated_at=?,next_attempt=? WHERE delivery_id=?',(delivery_status,stamp(),time.time()+60*(2**part['attempts']),item['delivery_id']))
                return item['delivery_id']
    with db.get_db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        fence(conn,item)
        conn.execute("UPDATE deliveries SET status='sent',updated_at=? WHERE delivery_id=?",(stamp(),item['delivery_id']))
    return item['delivery_id']


def list_deliveries():
    with db.get_db() as conn:
        return [dict(r) for r in conn.execute('''SELECT d.delivery_id,d.target_date,d.status,d.created_at,d.updated_at,
          COUNT(p.part) parts_total,SUM(p.status='sent') parts_sent FROM deliveries d JOIN delivery_parts p USING(delivery_id)
          GROUP BY d.delivery_id ORDER BY d.created_at DESC LIMIT 50''')]


def resolve(delivery_id):
    with db.get_db() as conn:
        conn.execute("UPDATE deliveries SET status='resolved',resolution='Acknowledged without resend',updated_at=? WHERE delivery_id=? AND status IN ('unknown','partial','blocked')",(stamp(),delivery_id))


def retry(delivery_id):
    with db.get_db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        unsafe=conn.execute("SELECT 1 FROM delivery_parts WHERE delivery_id=? AND status IN ('unknown','partial','sending')",(delivery_id,)).fetchone()
        if unsafe:
            raise ValueError('Uncertain or partial sends cannot be automatically retried')
        conn.execute("UPDATE deliveries SET status='queued',next_attempt=0,updated_at=? WHERE delivery_id=? AND status IN ('retryable','blocked')",(stamp(),delivery_id))
