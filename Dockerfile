# ============================================================
# Stock Tracker — Dockerfile
# 多阶段构建：减小最终镜像体积
# ============================================================

# ---------- Stage 1: 依赖安装 ----------
FROM python:3.12-slim AS builder

WORKDIR /build

# 安装编译依赖（部分 Python 包需要）
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---------- Stage 2: 运行镜像 ----------
FROM python:3.12-slim

LABEL maintainer="stock-tracker"
LABEL description="Stock Tracker Web Dashboard"

# 创建非 root 用户
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser

WORKDIR /app

# 从 builder 阶段复制已安装的依赖
COPY --from=builder /install /usr/local

# 复制项目代码
COPY . .

# 创建数据和日志目录
RUN mkdir -p data logs && \
    chown -R appuser:appuser /app

# 切换到非 root 用户
USER appuser

# 环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOST=0.0.0.0 \
    PORT=8000

EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/')" || exit 1

# 启动命令
CMD ["uvicorn", "web.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
