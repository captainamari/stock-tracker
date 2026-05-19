# ============================================================
# Stock Tracker — Dockerfile (V2: 含前端构建)
# 三阶段构建：Frontend → Python deps → Runtime
# ============================================================

# ---------- Stage 1: Frontend Build ----------
FROM node:18-slim AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --production=false 2>/dev/null || npm install
COPY frontend/ .
RUN npx vite build

# ---------- Stage 2: Python 依赖安装 ----------
FROM python:3.12-slim AS py-builder
WORKDIR /build
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc && \
    rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---------- Stage 3: 运行镜像 ----------
FROM python:3.12-slim

LABEL maintainer="stock-tracker"
LABEL description="Stock Tracker — Trading Intelligence Platform"

# 创建非 root 用户
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser

WORKDIR /app

# 从 builder 阶段复制已安装的 Python 依赖
COPY --from=py-builder /install /usr/local

# 复制项目代码（排除 frontend/node_modules）
COPY lib/ ./lib/
COPY scripts/ ./scripts/
COPY web/ ./web/
COPY config/ ./config/
COPY templates/ ./templates/
COPY requirements.txt .

# 从 frontend builder 复制构建产物到正确位置
COPY --from=frontend-builder /app/frontend/../web/static/app ./web/static/app/

# 创建数据和日志目录
RUN mkdir -p data logs && \
    chown -R appuser:appuser /app

# 切换到非 root 用户
USER appuser

# 环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUTF8=1 \
    HOST=0.0.0.0 \
    PORT=8000

EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/ws/status')" || exit 1

# 启动命令
CMD ["uvicorn", "web.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
