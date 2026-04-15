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

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.gzip import GZipMiddleware

from web.routes import dashboard, watchlist, ticker, api

# ============================================================
# App 初始化
# ============================================================
app = FastAPI(
    title="Stock Tracker Dashboard",
    description="美股技术分析与信号监控系统",
    version="4.0.0",
)

# Gzip 压缩
app.add_middleware(GZipMiddleware, minimum_size=500)

# 静态文件
STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

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
    import uvicorn
    uvicorn.run(
        "web.app:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        reload_dirs=[str(ROOT_DIR)],
    )
