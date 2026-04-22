#!/bin/bash
# Stock Tracker 每日数据更新脚本
# 建议在美股收盘后运行（美东时间 16:30 之后）
#
# 此脚本委托给 daily_pipeline.py（三阶段 Pipeline 引擎）执行：
#   Phase 1: 数据采集（价格拉取）
#   Phase 2: 策略计算 + DB 持久化
#   Phase 3: Telegram 推送（从 DB 读取，可独立重试）
#
# 用法:
#   bash scripts/daily_update.sh                    # 完整 pipeline
#   bash scripts/daily_update.sh --docker           # 强制 Docker 模式
#   bash scripts/daily_update.sh --venv             # 强制 venv 模式
#   bash scripts/daily_update.sh --notify-only      # 只推送（数据已在 DB）
#   bash scripts/daily_update.sh --no-notify        # 只更新数据，不推送
#   bash scripts/daily_update.sh --dry-run          # 渲染推送消息但不发送
#   bash scripts/daily_update.sh --force            # 强制重跑所有步骤
#   bash scripts/daily_update.sh --test-bot         # 测试 Telegram Bot 连通性

set -euo pipefail

# ======================== 配置 ========================
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

# 加载 .env（Telegram token 等配置）
if [ -f ".env" ]; then
    set -a
    source .env
    set +a
fi

# ======================== 运行模式检测 ========================
MODE=""
PIPELINE_ARGS=()

# 解析参数：分离 --docker/--venv（Shell 专用）和其他参数（传给 pipeline.py）
for arg in "$@"; do
    case "$arg" in
        --docker) MODE="docker" ;;
        --venv)   MODE="venv" ;;
        *)        PIPELINE_ARGS+=("$arg") ;;
    esac
done

# 自动检测运行环境
if [ -z "$MODE" ]; then
    if command -v docker &>/dev/null && sudo docker compose ps --status running 2>/dev/null | grep -q "stock-tracker"; then
        MODE="docker"
    elif [ -f "venv/bin/activate" ] || [ -f ".venv/bin/activate" ]; then
        MODE="venv"
    else
        echo "❌ 未检测到可用的运行环境（Docker 容器未运行，虚拟环境不存在）"
        exit 1
    fi
fi

# ======================== 执行 Pipeline ========================
if [ "$MODE" = "docker" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 运行模式: Docker"
    exec sudo docker compose exec -T web python scripts/daily_pipeline.py "${PIPELINE_ARGS[@]}"
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 运行模式: 虚拟环境 (venv)"
    if [ -f "venv/bin/activate" ]; then
        source venv/bin/activate
    elif [ -f ".venv/bin/activate" ]; then
        source .venv/bin/activate
    else
        echo "❌ 未找到虚拟环境 (venv/ 或 .venv/)"
        exit 1
    fi
    exec python3 scripts/daily_pipeline.py "${PIPELINE_ARGS[@]}"
fi
