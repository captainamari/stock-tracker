# 部署指南 V2 — 重构后项目

## 目录

- [一、部署架构变化](#一部署架构变化)
- [二、数据迁移方案](#二数据迁移方案)
- [三、云服务器更新步骤](#三云服务器更新步骤)
- [四、Docker 部署（推荐）](#四docker-部署推荐)
- [五、定时任务配置](#五定时任务配置)
- [六、回滚方案](#六回滚方案)

---

## 一、部署架构变化

### 旧架构 vs 新架构

| 维度 | 旧版 | 新版 |
|------|------|------|
| 前端 | Jinja2 SSR (服务端渲染) | React SPA + SSR 并存 |
| API | 单一 `/api/*` (10 端点) | `/api/*` (旧) + `/api/v1/*` (18 端点) |
| 策略 | 各自独立脚本 | 统一 Registry + Pipeline |
| 实时性 | SSE (价格刷新) | WebSocket (信号/Score/刷新) |
| 数据库 | 9 张表 | 13 张表 (新增 4 张) |
| Pipeline | 5 策略 | 6 策略 (+momentum_v3) |

### 关键点：100% 向后兼容

- 旧的 `/` `/watchlist` `/ticker` 页面 **完全保留**
- 旧的 `/api/*` 端点 **不变**
- 新 SPA 在 `/app` 路径，不影响旧功能
- 数据库只新增表，**不修改**任何现有表结构

---

## 二、数据迁移方案

### 迁移原则：零停机、零数据丢失

由于新架构只是 **新增** 表和功能，不修改现有数据结构，所以：

1. **现有数据无需迁移** — `stock_prices`, `strategy_results`, `signal_changes` 等表保持原样
2. **只需运行迁移脚本** — 新增 4 张表 + 初始化板块配置
3. **首次运行 momentum_v3** 会自动填充新表数据

### 迁移步骤

```bash
# SSH 到服务器后执行（在项目目录内）

# 1. 备份现有数据库（重要！）
cp data/stock_tracker.db data/stock_tracker_backup_$(date +%Y%m%d).db

# 2. 运行迁移（新增 momentum_scores, sector_mappings 等表）
python -m lib.db migrate

# 3. 首次运行 Momentum V3 Pipeline（填充新表数据）
python -m lib.strategy.momentum_v3.runner

# 4. 验证
python -c "from lib.db import get_momentum_scores; print(f'Momentum scores: {len(get_momentum_scores())}')"
```

### 数据库版本变化

```
v1.1.0 (旧) → v1.2.0 (新)
新增表：
  - momentum_scores    (动量评分，三层)
  - sector_mappings    (股票→板块映射)
  - sector_definitions (板块 ETF 配置)
  - score_history      (评分走势图数据)
```

---

## 三、云服务器更新步骤

### 方式 A：Docker 部署（推荐，最简单）

```bash
# 1. SSH 到服务器
ssh your-server

# 2. 进入项目目录
cd /path/to/stock-tracker

# 3. 备份数据
docker compose exec web cp /app/data/stock_tracker.db /app/data/stock_tracker_backup.db

# 4. 拉取最新代码
git pull origin main

# 5. 重新构建并启动（自动处理前端构建）
docker compose up -d --build

# 6. 运行数据库迁移（容器内执行）
docker compose exec web python -m lib.db migrate

# 7. 首次运行 Momentum V3
docker compose exec web python -m lib.strategy.momentum_v3.runner

# 8. 验证
docker compose exec web python -c "from lib.db import get_momentum_scores; print(len(get_momentum_scores()))"
curl http://localhost:8000/api/v1/strategies/
curl http://localhost:8000/app
```

### 方式 B：非 Docker 部署（Systemd + venv）

```bash
# 1. 停止服务
sudo systemctl stop stock-tracker

# 2. 备份
cp data/stock_tracker.db data/stock_tracker_backup_$(date +%Y%m%d).db

# 3. 拉取代码
git pull origin main

# 4. 更新 Python 依赖（无新增依赖，此步可选）
source venv/bin/activate
pip install -r requirements.txt

# 5. 构建前端（如果需要修改前端时）
cd frontend && npm install && npx vite build && cd ..

# 6. 运行迁移
python -m lib.db migrate

# 7. 重启服务
sudo systemctl start stock-tracker

# 8. 运行 Momentum V3 首次计算
python -m lib.strategy.momentum_v3.runner

# 9. 验证
curl http://localhost:8000/api/v1/strategies/
```

---

## 四、Docker 部署（推荐）

### 更新后的 Dockerfile

需要在构建时加入前端构建步骤。更新 Dockerfile：

```dockerfile
# ============================================================
# Stock Tracker — Dockerfile (V2: 含前端构建)
# ============================================================

# ---------- Stage 1: Frontend Build ----------
FROM node:18-slim AS frontend-builder
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --production=false
COPY frontend/ .
RUN npx vite build

# ---------- Stage 2: Python 依赖 ----------
FROM python:3.12-slim AS py-builder
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---------- Stage 3: 运行镜像 ----------
FROM python:3.12-slim
LABEL maintainer="stock-tracker"

RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser
WORKDIR /app

# Python 依赖
COPY --from=py-builder /install /usr/local

# 项目代码
COPY . .

# 前端构建产物
COPY --from=frontend-builder /frontend/../web/static/app ./web/static/app

# 数据目录
RUN mkdir -p data logs && chown -R appuser:appuser /app

USER appuser

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUTF8=1 \
    HOST=0.0.0.0 \
    PORT=8000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/ws/status')" || exit 1

CMD ["uvicorn", "web.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
```

### docker-compose.yml (更新版)

```yaml
services:
  web:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: stock-tracker
    restart: unless-stopped
    ports:
      - "8000:8000"
    volumes:
      - stock-data:/app/data
      - stock-logs:/app/logs
    environment:
      - HOST=0.0.0.0
      - PORT=8000
      - PYTHONUTF8=1
      - TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN:-}
      - TELEGRAM_CHAT_ID=${TELEGRAM_CHAT_ID:-}
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/ws/status')"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 15s

volumes:
  stock-data:
    driver: local
  stock-logs:
    driver: local
```

---

## 五、定时任务配置

### Cron 配置（容器外）

```bash
# 编辑 crontab
crontab -e

# ─── 每日数据更新 (美东时间 16:30，即收盘后30分钟) ───
# 如果服务器是 UTC 时区: 16:30 ET = 20:30 UTC (冬令) / 21:30 UTC (夏令)
30 20 * * 1-5 docker compose -f /path/to/stock-tracker/docker-compose.yml exec -T web python scripts/daily_pipeline.py >> /var/log/stock-tracker-cron.log 2>&1

# ─── 备选：如果不用 Docker ───
30 20 * * 1-5 cd /path/to/stock-tracker && /path/to/venv/bin/python scripts/daily_pipeline.py >> logs/cron.log 2>&1
```

### Pipeline 执行顺序（自动包含 Momentum V3）

```
daily_pipeline.py 执行顺序:
  Phase 1: prices (yfinance fetch)
  Phase 2: market_pulse → momentum_v3 → stage2 → vcp → bottom_fisher → buying_checklist
  Phase 3: Telegram notification
```

`momentum_v3` 已自动集成到 Pipeline Phase 2 中，**无需额外配置**。

### 手动触发（Web 页面 / API）

```bash
# 通过 API 触发动量刷新
curl -X POST http://localhost:8000/api/v1/momentum/refresh

# 通过 API 触发价格刷新（原有 SSE 方式仍可用）
curl -X POST http://localhost:8000/api/prices/refresh
```

---

## 六、回滚方案

如果更新后出现问题：

```bash
# 方式 1：Git 回滚
git checkout <previous-commit>
docker compose up -d --build

# 方式 2：数据库回滚（如果迁移出问题）
docker compose exec web cp /app/data/stock_tracker_backup.db /app/data/stock_tracker.db
docker compose restart web

# 方式 3：仅回滚到旧前端
# 新架构下旧页面仍在 / 路径，直接访问 http://your-domain/ 即可
# 新 SPA 在 /app，不影响旧功能
```

### 安全检查清单

- [ ] 备份数据库 `stock_tracker.db`
- [ ] 确认 `git pull` 无冲突
- [ ] `docker compose up -d --build` 成功
- [ ] `python -m lib.db migrate` 无报错
- [ ] `curl /api/v1/strategies/` 返回 8 个策略
- [ ] `curl /app` 返回 HTML (SPA)
- [ ] `curl /` 返回旧 dashboard (SSR 保留)
- [ ] Telegram 推送正常 (检查 `docker compose logs web`)
- [ ] Cron 次日执行正常

---

## 总结：更新操作最小化

对于已经在运行的云服务器，**最小化更新步骤**只有 4 步：

```bash
git pull origin main                          # 1. 拉代码
docker compose up -d --build                  # 2. 重建容器
docker compose exec web python -m lib.db migrate  # 3. 跑迁移
docker compose exec web python -m lib.strategy.momentum_v3.runner  # 4. 首次计算
```

之后 Cron 定时任务会自动执行 `daily_pipeline.py`，其中已包含 `momentum_v3` 策略。
