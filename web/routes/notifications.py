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
    report_scope: str | None = None
    report_mode: str | None = None


@router.get('/settings')
def read_settings(request:Request):
    require_admin(request)
    return {**get_schedule(),'hub_configured':bool(settings().hub_url and settings().hub_token)}


@router.put('/settings')
def write_settings(payload:Schedule):
    try:
        save_schedule(payload.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from exc
    return {'status':'saved'}


@router.get('/notifications/preview')
def preview(request: Request, scope: str = 'personal', mode: str = 'standard'):
    require_admin(request)
    if scope not in ('following','held','personal') or mode not in ('standard','compact'):
        raise HTTPException(422, 'Invalid scope or mode')
    from lib import db
    from lib.daily_reports import notification_preview
    from lib.market_calendar import completed_session
    target = completed_session()
    with db.get_db() as conn:
        identifier, body = notification_preview(conn, target, scope, mode)
    parts = delivery.split_message(body)
    return {'report_id': identifier, 'target_date': target, 'parts': parts, 'count': len(parts)}


@router.get('/notifications')
def notifications(request:Request,page:int | None=None,size:int=20):
    require_admin(request)
    if page is None:
        return delivery.list_deliveries()  # Preserve existing API clients.
    from lib.listing import paginate
    return paginate(delivery.list_deliveries(limit=-1),page,size)


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
