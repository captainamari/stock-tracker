"""
Stock Tracker — Web Dashboard
FastAPI 主入口，提供 Dashboard / Watchlist / Ticker Detail 三个核心页面。

启动方式:
    python -m web.app
    或
    uvicorn web.app:app --reload --port 8000
"""

import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中
ROOT_DIR = Path(__file__).parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from starlette.middleware.gzip import GZipMiddleware

from web.routes import dashboard, watchlist, ticker, api
from web.i18n import get_language_from_request, SUPPORTED_LANGUAGES

# ============================================================
# App 初始化
# ============================================================
app = FastAPI(
    title="Stock Tracker Dashboard",
    description="US Stock Technical Analysis & Signal Monitoring System",
    version="4.0.0",
)

# Gzip 压缩
app.add_middleware(GZipMiddleware, minimum_size=500)

# 静态文件
STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ============================================================
# 语言切换端点 — 设置 Cookie 并重定向回来
# ============================================================
@app.get("/set-lang/{lang}")
async def set_language(request: Request, lang: str):
    """切换界面语言，写入 Cookie 后重定向回 Referer 或首页"""
    if lang not in SUPPORTED_LANGUAGES:
        lang = "en"
    referer = request.headers.get("referer", "/")
    response = RedirectResponse(url=referer, status_code=302)
    response.set_cookie("lang", lang, max_age=365 * 24 * 3600, httponly=False, samesite="lax")
    return response

# ============================================================
# 注册路由
# ============================================================
app.include_router(dashboard.router)
app.include_router(watchlist.router)
app.include_router(ticker.router)
app.include_router(api.router, prefix="/api")

# ============================================================
# CLI 入口
# ============================================================
if __name__ == "__main__":
    import os
    import uvicorn

    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    reload = os.environ.get("RELOAD", "true").lower() == "true"

    uvicorn.run(
        "web.app:app",
        host=host,
        port=port,
        reload=reload,
        reload_dirs=[str(ROOT_DIR)] if reload else None,
    )
