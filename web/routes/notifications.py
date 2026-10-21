from fastapi import APIRouter,Request,HTTPException
from pydantic import BaseModel,ConfigDict
from lib.schedule import get_schedule,save_schedule
from lib import delivery
from lib.settings import settings
from web.auth import require_admin

router=APIRouter(prefix='/api')


class Schedule(BaseModel):
    model_config=ConfigDict(extra='forbid')
    update_time: str
    notify_time: str
    channel: str
    enabled: bool


@router.get('/settings')
def read_settings(request:Request):
    require_admin(request)
    return {**get_schedule(),'hub_configured':bool(settings().hub_url and settings().hub_token)}


@router.put('/settings')
def write_settings(payload:Schedule):
    try:
        save_schedule(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from exc
    return {'status':'saved'}


@router.get('/notifications')
def notifications(request:Request):
    require_admin(request)
    return delivery.list_deliveries()


@router.post('/notifications/test')
def test_notification():
    return {'delivery_id':delivery.queue_test()}


@router.post('/notifications/{delivery_id}/resolve')
def resolve(delivery_id:str):
    delivery.resolve(delivery_id)
    return {'status':'resolved'}


@router.post('/notifications/{delivery_id}/retry')
def retry(delivery_id:str):
    try:
        delivery.retry(delivery_id)
    except ValueError as exc:
        raise HTTPException(409,str(exc)) from exc
    return {'status':'queued'}
