#!/bin/bash
# Stock Tracker 每日数据更新脚本
# 建议在美股收盘后运行（美东时间 16:30 之后）
#
# 用法:
#   bash scripts/daily_update.sh          # 正常运行
#   bash scripts/daily_update.sh --test   # 仅打印命令，不实际执行

set -euo pipefail

# 自动检测项目根目录（脚本所在目录的上一级）
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

# 激活虚拟环境
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
elif [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
else
    echo "❌ 未找到虚拟环境 (venv/ 或 .venv/)"
    exit 1
fi

# 日志设置
mkdir -p logs
LOG_FILE="logs/daily_update_$(date +%Y%m%d).log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

log "========================================"
log "Stock Tracker 每日更新开始"
log "项目目录: $PROJECT_DIR"
log "Python: $(python3 --version)"
log "========================================"

# Step 1: 拉取价格数据
log "[1/5] 拉取价格数据 (yfinance)..."
if python3 scripts/save_prices_yfinance.py --mode all >> "$LOG_FILE" 2>&1; then
    log "[1/5] ✅ 价格数据拉取成功"
else
    log "[1/5] ⚠️ 价格数据拉取失败（继续执行后续策略）"
fi

# Step 2: Market Pulse
log "[2/5] 运行 Market Pulse..."
if python3 scripts/market_pulse.py --cron >> "$LOG_FILE" 2>&1; then
    log "[2/5] ✅ Market Pulse 完成"
else
    log "[2/5] ⚠️ Market Pulse 失败"
fi

# Step 3: Stage 2 Monitor
log "[3/5] 运行 Stage 2 Monitor..."
if python3 scripts/stage2_monitor.py --cron >> "$LOG_FILE" 2>&1; then
    log "[3/5] ✅ Stage 2 Monitor 完成"
else
    log "[3/5] ⚠️ Stage 2 Monitor 失败"
fi

# Step 4: VCP Scanner
log "[4/5] 运行 VCP Scanner..."
if python3 scripts/vcp_scanner.py --cron >> "$LOG_FILE" 2>&1; then
    log "[4/5] ✅ VCP Scanner 完成"
else
    log "[4/5] ⚠️ VCP Scanner 失败"
fi

# Step 5: Bottom Fisher
log "[5/5] 运行 Bottom Fisher..."
if python3 scripts/bottom_fisher.py --cron >> "$LOG_FILE" 2>&1; then
    log "[5/5] ✅ Bottom Fisher 完成"
else
    log "[5/5] ⚠️ Bottom Fisher 失败"
fi

log "========================================"
log "每日更新完成！"
log "========================================"

# 清理 30 天前的日志
find "$PROJECT_DIR/logs" -name "daily_update_*.log" -mtime +30 -delete 2>/dev/null || true

echo ""
echo "📋 完整日志: $LOG_FILE"
