"""Exercise the pinned real hub ASGI application, with only provider I/O replaced.

Run: python -m scripts.verify_hub_contract --checkout ../notification-hub
No real Telegram/Email call is made. No hub files are modified.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

PIN='7c6ef039047e9adae7c6ca14d4e32204f352957c'

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkout',type=Path,required=True)
    args=parser.parse_args()
    sha=subprocess.check_output(['git','-C',str(args.checkout),'rev-parse','HEAD'],text=True).strip()
    assert sha==PIN, f'Expected pinned contract {PIN}, got {sha}'
    sys.path.insert(0,str(args.checkout.resolve()))
    from app.config import Settings
    from app.main import create_app
    from app.notifier import NotificationService
    from fastapi.testclient import TestClient
    from lib.delivery import HubClient
    token='isolated-contract-test-token'
    os.environ['NOTIFICATION_API_URL']='http://testserver'
    os.environ['NOTIFICATION_API_TOKEN']=token
    settings=Settings(_env_file=None,api_token=token,telegram_apprise_url='mock://telegram',email_apprise_url='mock://email')
    calls=[]
    service=NotificationService(settings)
    service._send_with_apprise=lambda url,title,body,level: calls.append((url,title,body,level)) or True
    payload=dict(target_date='2026-10-20',channel='trading',report_id='isolated-synthetic-report')
    part=dict(part=1,body='Synthetic contract verification — no external provider')
    with TestClient(create_app(settings,service)) as client:
        adapter=HubClient(client)
        status,receipt,error=adapter.send(payload,part,1)
        assert status=='sent' and receipt['delivered_to']==['telegram'] and receipt['request_id'] and error is None
        assert len(calls)==1 and 'Source: stock-tracker' in calls[0][2]
        os.environ['NOTIFICATION_API_TOKEN']='incorrect-contract-token'
        assert adapter.send(payload,part,1)[0]=='blocked'
        assert len(calls)==1
        os.environ['NOTIFICATION_API_TOKEN']=token
        payload['channel']='warning'
        service._send_with_apprise=lambda url,*_: url!='mock://email'
        assert adapter.send(payload,part,1)[0]=='partial'
        service._send_with_apprise=lambda *args: False
        assert adapter.send(payload,part,1)[0]=='unknown'
        payload['channel']='nonexistent'
        assert adapter.send(payload,part,1)[0]=='blocked'
    empty=Settings(_env_file=None,api_token=token)
    with TestClient(create_app(empty,NotificationService(empty))) as client:
        payload['channel']='trading'
        assert HubClient(client).send(payload,part,1)[0]=='blocked'
    print(json.dumps({'hub_commit':sha,'real_asgi_contract':'passed','cases':['sent receipt','bearer rejection','partial','all provider failure ambiguous','unknown channel','unconfigured provider'],'external_sends':0},indent=2))

if __name__=='__main__':
    main()
