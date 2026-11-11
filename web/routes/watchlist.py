from fastapi import APIRouter, Request
from lib.guest import summary
from web.deps import render
router=APIRouter()

@router.get('/watchlist')
@router.get('/discover')
def watchlist_page(request: Request, batch: str | None=None):
    return render(request,'guest.html',dict(**summary(batch), view='discover' if request.url.path=='/discover' else 'watchlist'))
