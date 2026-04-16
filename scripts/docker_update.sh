#!/bin/bash
# ============================================================
# Stock Tracker — Docker 代码更新脚本
# ============================================================
# 用法:
#   bash scripts/docker_update.sh           # 正常更新
#   bash scripts/docker_update.sh --force   # 强制重建（含依赖更新）
#   bash scripts/docker_update.sh --status  # 仅查看状态
#
# 功能:
#   1. 拉取远程仓库最新代码
#   2. 重新构建 Docker 镜像
#   3. 滚动更新容器（数据卷不受影响）
#   4. 清理旧镜像释放磁盘空间
#   5. 验证服务健康状态
# ============================================================

set -euo pipefail

# -------------------- 配置 --------------------
PROJECT_DIR="/home/opc/stock-tracker"
BRANCH="main"
CONTAINER_NAME="stock-tracker"
HEALTH_URL="http://127.0.0.1:8000/"
HEALTH_TIMEOUT=60          # 健康检查超时（秒）
BACKUP_DB=true             # 更新前是否自动备份数据库
LOG_DIR="${PROJECT_DIR}/logs"
LOG_FILE="${LOG_DIR}/docker_update_$(date +%Y%m%d_%H%M%S).log"

# -------------------- 颜色输出 --------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log()   { echo -e "${BLUE}[$(date '+%H:%M:%S')]${NC} $*" | tee -a "$LOG_FILE"; }
ok()    { echo -e "${GREEN}[$(date '+%H:%M:%S')] ✅ $*${NC}" | tee -a "$LOG_FILE"; }
warn()  { echo -e "${YELLOW}[$(date '+%H:%M:%S')] ⚠️  $*${NC}" | tee -a "$LOG_FILE"; }
error() { echo -e "${RED}[$(date '+%H:%M:%S')] ❌ $*${NC}" | tee -a "$LOG_FILE"; }

# -------------------- 前置检查 --------------------
preflight_check() {
    log "前置检查..."

    # 检查项目目录
    if [ ! -d "$PROJECT_DIR" ]; then
        error "项目目录不存在: $PROJECT_DIR"
        exit 1
    fi

    # 检查 docker
    if ! command -v docker &> /dev/null; then
        error "Docker 未安装，请先安装 Docker"
        exit 1
    fi

    # 检查 docker compose
    if ! docker compose version &> /dev/null; then
        error "Docker Compose 不可用"
        exit 1
    fi

    # 检查 git
    if ! command -v git &> /dev/null; then
        error "Git 未安装"
        exit 1
    fi

    ok "前置检查通过"
}

# -------------------- 查看状态 --------------------
show_status() {
    echo ""
    log "========== 当前部署状态 =========="

    cd "$PROJECT_DIR"

    # Git 信息
    echo ""
    log "📌 Git 状态:"
    echo "   分支: $(git branch --show-current)"
    echo "   最新提交: $(git log -1 --format='%h %s (%cr)' 2>/dev/null || echo '未知')"
    echo "   远程地址: $(git remote get-url origin 2>/dev/null || echo '未配置')"

    # 容器状态
    echo ""
    log "🐳 容器状态:"
    docker compose ps 2>/dev/null || echo "   容器未运行"

    # 镜像信息
    echo ""
    log "📦 镜像信息:"
    docker images --filter "reference=*stock-tracker*" --format "   {{.Repository}}:{{.Tag}}  {{.Size}}  创建于 {{.CreatedSince}}" 2>/dev/null || echo "   无相关镜像"

    # 磁盘使用
    echo ""
    log "💾 Docker 磁盘使用:"
    docker system df 2>/dev/null | head -5

    # 健康检查
    echo ""
    if curl -sf --max-time 5 "$HEALTH_URL" > /dev/null 2>&1; then
        ok "服务健康: $HEALTH_URL 可访问"
    else
        warn "服务不可达: $HEALTH_URL"
    fi

    echo ""
}

# -------------------- 备份数据库 --------------------
backup_database() {
    if [ "$BACKUP_DB" != true ]; then
        return
    fi

    log "备份数据库..."

    local backup_dir="${PROJECT_DIR}/backups"
    local backup_file="stock_tracker_$(date +%Y%m%d_%H%M%S).db"
    mkdir -p "$backup_dir"

    # 从 Docker 数据卷复制数据库
    if docker compose cp "${CONTAINER_NAME}:/app/data/stock_tracker.db" "${backup_dir}/${backup_file}" 2>/dev/null; then
        ok "数据库已备份: backups/${backup_file}"

        # 清理 7 天前的备份
        find "$backup_dir" -name "stock_tracker_*.db" -mtime +7 -delete 2>/dev/null
        log "已清理 7 天前的旧备份"
    else
        warn "数据库备份跳过（容器未运行或数据库不存在）"
    fi
}

# -------------------- 拉取最新代码 --------------------
pull_latest_code() {
    log "拉取远程仓库最新代码..."

    cd "$PROJECT_DIR"

    # 记录更新前的 commit
    local old_commit
    old_commit=$(git rev-parse --short HEAD 2>/dev/null || echo "未知")

    # 检查是否有未提交的本地修改
    if ! git diff --quiet 2>/dev/null || ! git diff --cached --quiet 2>/dev/null; then
        warn "检测到本地未提交的修改"
        log "暂存本地修改 (git stash)..."
        git stash push -m "auto-stash before docker_update $(date +%Y%m%d_%H%M%S)"
        local stashed=true
    fi

    # 拉取最新代码
    if git pull origin "$BRANCH" 2>&1 | tee -a "$LOG_FILE"; then
        local new_commit
        new_commit=$(git rev-parse --short HEAD)

        if [ "$old_commit" = "$new_commit" ]; then
            log "代码已是最新 (${new_commit})，无需更新"
            # 恢复 stash
            if [ "${stashed:-false}" = true ]; then
                git stash pop 2>/dev/null || true
            fi
            return 1  # 返回 1 表示没有新代码
        fi

        ok "代码已更新: ${old_commit} → ${new_commit}"

        # 显示更新内容摘要
        log "更新内容:"
        git log --oneline "${old_commit}..${new_commit}" 2>/dev/null | while read -r line; do
            echo "   $line"
        done

        # 显示变更文件
        log "变更文件:"
        git diff --stat "${old_commit}..${new_commit}" 2>/dev/null | tail -5 | while read -r line; do
            echo "   $line"
        done
    else
        error "代码拉取失败"
        # 恢复 stash
        if [ "${stashed:-false}" = true ]; then
            git stash pop 2>/dev/null || true
        fi
        exit 1
    fi

    # 恢复 stash
    if [ "${stashed:-false}" = true ]; then
        log "恢复暂存的本地修改..."
        git stash pop 2>/dev/null || warn "stash 恢复失败，请手动处理: git stash list"
    fi

    return 0  # 返回 0 表示有新代码
}

# -------------------- 重建 Docker 镜像 & 重启容器 --------------------
rebuild_and_restart() {
    local force="${1:-false}"

    cd "$PROJECT_DIR"

    log "重新构建 Docker 镜像..."

    local build_args=""
    if [ "$force" = true ]; then
        build_args="--no-cache"
        log "强制模式: 不使用缓存，完全重建"
    fi

    # 构建镜像
    if docker compose build $build_args 2>&1 | tee -a "$LOG_FILE"; then
        ok "镜像构建成功"
    else
        error "镜像构建失败"
        exit 1
    fi

    # 重启容器（使用新镜像）
    log "重启容器..."
    docker compose up -d 2>&1 | tee -a "$LOG_FILE"

    ok "容器已重启"
}

# -------------------- 健康检查 --------------------
health_check() {
    log "等待服务启动 (最多 ${HEALTH_TIMEOUT}s)..."

    local elapsed=0
    local interval=3

    while [ $elapsed -lt $HEALTH_TIMEOUT ]; do
        if curl -sf --max-time 5 "$HEALTH_URL" > /dev/null 2>&1; then
            ok "服务已就绪! (${elapsed}s)"
            return 0
        fi
        sleep $interval
        elapsed=$((elapsed + interval))
        echo -n "."
    done

    echo ""
    error "服务启动超时 (${HEALTH_TIMEOUT}s)"
    log "查看容器日志排查:"
    docker compose logs --tail=20 2>/dev/null
    return 1
}

# -------------------- 清理旧镜像 --------------------
cleanup() {
    log "清理悬空镜像..."
    local cleaned
    cleaned=$(docker image prune -f 2>/dev/null | tail -1)
    log "   $cleaned"

    # 清理 30 天前的更新日志
    find "$LOG_DIR" -name "docker_update_*.log" -mtime +30 -delete 2>/dev/null
}

# -------------------- 主流程 --------------------
main() {
    local force=false
    local status_only=false

    # 解析参数
    for arg in "$@"; do
        case $arg in
            --force)  force=true ;;
            --status) status_only=true ;;
            --help|-h)
                echo "用法: bash scripts/docker_update.sh [选项]"
                echo ""
                echo "选项:"
                echo "  (无参数)    正常更新：拉取代码 → 重建镜像 → 重启容器"
                echo "  --force     强制重建：不使用 Docker 缓存，完全重新构建"
                echo "  --status    仅查看当前部署状态"
                echo "  --help      显示此帮助信息"
                exit 0
                ;;
            *)
                error "未知参数: $arg  (使用 --help 查看用法)"
                exit 1
                ;;
        esac
    done

    # 创建日志目录
    mkdir -p "$LOG_DIR"

    # 仅查看状态
    if [ "$status_only" = true ]; then
        show_status
        exit 0
    fi

    echo ""
    echo "============================================"
    echo "  🚀 Stock Tracker Docker 代码更新"
    echo "  $(date '+%Y-%m-%d %H:%M:%S')"
    echo "============================================"
    echo ""

    # Step 1: 前置检查
    preflight_check

    # Step 2: 备份数据库
    backup_database

    # Step 3: 拉取最新代码
    local has_updates=true
    if ! pull_latest_code; then
        has_updates=false
    fi

    # Step 4: 重建镜像 & 重启容器
    if [ "$has_updates" = true ] || [ "$force" = true ]; then
        rebuild_and_restart "$force"
    else
        log "无代码变更且非强制模式，跳过重建"
        log "如需强制重建，请使用: bash scripts/docker_update.sh --force"
        exit 0
    fi

    # Step 5: 健康检查
    health_check

    # Step 6: 清理
    cleanup

    # 完成
    echo ""
    echo "============================================"
    ok "更新完成!"
    echo "============================================"
    echo ""
    log "📌 当前版本: $(cd "$PROJECT_DIR" && git log -1 --format='%h %s')"
    log "📌 容器状态:"
    docker compose -f "${PROJECT_DIR}/docker-compose.yml" ps 2>/dev/null
    log "📌 更新日志: $LOG_FILE"
    echo ""
}

main "$@"
