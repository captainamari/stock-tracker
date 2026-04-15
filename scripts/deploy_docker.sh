#!/bin/bash
# ============================================================
# Stock Tracker — Oracle Cloud Docker 一键部署脚本
# ============================================================
# 适用系统: Ubuntu 22.04/24.04 (Oracle Cloud ARM/AMD 实例)
#
# 用法:
#   # 首次部署（完整安装 + 构建 + 初始化数据）
#   bash scripts/deploy_docker.sh
#
#   # 更新代码后重新部署
#   bash scripts/deploy_docker.sh --update
#
#   # 仅重启服务
#   bash scripts/deploy_docker.sh --restart
#
#   # 查看状态
#   bash scripts/deploy_docker.sh --status
# ============================================================

set -euo pipefail

# ======================== 配置区 ========================
# ⚠️ 部署前请修改以下变量
PROJECT_DIR="/opt/stock-tracker"
DOMAIN=""                        # 你的域名，例如 stocks.example.com（留空则跳过 Nginx/SSL）
EMAIL=""                         # 用于 Let's Encrypt 证书申请的邮箱
GIT_REPO=""                      # Git 仓库地址，例如 https://github.com/user/stock-tracker.git
GIT_BRANCH="main"                # Git 分支

# Cron 时间 (UTC)：默认 UTC 05:00 = 美东 01:00 = 北京 13:00
CRON_HOUR="5"
CRON_MINUTE="0"
# ========================================================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info()  { echo -e "${GREEN}[INFO]${NC}  $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_step()  { echo -e "\n${BLUE}========== $1 ==========${NC}"; }

# --------------------------------------------------------
# 检查是否以 root 运行或有 sudo 权限
# --------------------------------------------------------
check_sudo() {
    if [ "$EUID" -ne 0 ]; then
        if ! sudo -n true 2>/dev/null; then
            log_error "此脚本需要 sudo 权限，请使用 sudo 运行或配置免密 sudo"
            exit 1
        fi
    fi
}

# --------------------------------------------------------
# Step 1: 安装 Docker
# --------------------------------------------------------
install_docker() {
    log_step "Step 1: 安装 Docker"

    if command -v docker &>/dev/null; then
        log_info "Docker 已安装: $(docker --version)"
    else
        log_info "正在安装 Docker..."
        sudo apt-get update
        sudo apt-get install -y ca-certificates curl gnupg

        # 添加 Docker 官方 GPG key
        sudo install -m 0755 -d /etc/apt/keyrings
        curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
        sudo chmod a+r /etc/apt/keyrings/docker.gpg

        # 添加 Docker apt 源
        echo \
            "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
            $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
            sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

        sudo apt-get update
        sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

        # 将当前用户加入 docker 组（免 sudo 使用 docker）
        sudo usermod -aG docker "$USER"

        log_info "Docker 安装完成: $(docker --version)"
        log_warn "已将用户 $USER 加入 docker 组，首次使用可能需要重新登录 SSH"
    fi

    # 确保 Docker 服务在运行
    sudo systemctl start docker
    sudo systemctl enable docker
}

# --------------------------------------------------------
# Step 2: 拉取/更新代码
# --------------------------------------------------------
setup_code() {
    log_step "Step 2: 拉取代码"

    if [ -d "$PROJECT_DIR/.git" ]; then
        log_info "项目目录已存在，拉取最新代码..."
        cd "$PROJECT_DIR"
        git pull origin "$GIT_BRANCH"
    else
        if [ -z "$GIT_REPO" ]; then
            log_error "GIT_REPO 未设置！请修改脚本顶部的 GIT_REPO 变量"
            log_info "或者手动将代码放到 $PROJECT_DIR 目录下"
            exit 1
        fi

        log_info "克隆仓库: $GIT_REPO"
        sudo mkdir -p "$PROJECT_DIR"
        sudo chown "$USER:$USER" "$PROJECT_DIR"
        git clone -b "$GIT_BRANCH" "$GIT_REPO" "$PROJECT_DIR"
    fi

    cd "$PROJECT_DIR"
    log_info "代码准备完毕: $PROJECT_DIR"
}

# --------------------------------------------------------
# Step 3: 构建 Docker 镜像
# --------------------------------------------------------
build_image() {
    log_step "Step 3: 构建 Docker 镜像"
    cd "$PROJECT_DIR"

    log_info "构建镜像中（首次可能需要几分钟）..."
    sudo docker compose build --no-cache
    log_info "镜像构建完成"
}

# --------------------------------------------------------
# Step 4: 启动容器
# --------------------------------------------------------
start_container() {
    log_step "Step 4: 启动容器"
    cd "$PROJECT_DIR"

    # 停止旧容器（如果存在）
    sudo docker compose down 2>/dev/null || true

    # 启动新容器
    sudo docker compose up -d
    log_info "容器已启动"

    # 等待健康检查通过
    log_info "等待服务就绪..."
    for i in $(seq 1 30); do
        if sudo docker compose exec -T web python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/')" 2>/dev/null; then
            log_info "✅ Web 服务已就绪!"
            break
        fi
        if [ "$i" -eq 30 ]; then
            log_warn "服务启动超时，请检查日志: sudo docker compose logs"
        fi
        sleep 2
    done
}

# --------------------------------------------------------
# Step 5: 初始化数据库 & 数据
# --------------------------------------------------------
init_data() {
    log_step "Step 5: 初始化数据库 & 数据"
    cd "$PROJECT_DIR"

    log_info "[1/6] 初始化数据库 Schema..."
    sudo docker compose exec -T web python -m lib.db init

    log_info "[2/6] 同步观察列表..."
    sudo docker compose exec -T web python lib/config.py

    log_info "[3/6] 拉取价格数据（可能需要几分钟）..."
    sudo docker compose exec -T web python scripts/save_prices_yfinance.py --mode all

    log_info "[4/6] 运行 Market Pulse..."
    sudo docker compose exec -T web python scripts/market_pulse.py --cron

    log_info "[5/6] 运行 Stage 2 Monitor..."
    sudo docker compose exec -T web python scripts/stage2_monitor.py --cron

    log_info "[6/6] 运行策略扫描..."
    sudo docker compose exec -T web python scripts/vcp_scanner.py --cron
    sudo docker compose exec -T web python scripts/bottom_fisher.py --cron

    log_info "✅ 数据初始化完成"
}

# --------------------------------------------------------
# Step 6: 安装 Nginx 反向代理 + HTTPS
# --------------------------------------------------------
setup_nginx() {
    if [ -z "$DOMAIN" ]; then
        log_warn "未设置域名 (DOMAIN)，跳过 Nginx/SSL 配置"
        log_info "你可以直接通过 http://<服务器IP>:8000 访问"
        return
    fi

    log_step "Step 6: 配置 Nginx 反向代理"

    sudo apt-get install -y nginx certbot python3-certbot-nginx

    # 写入 Nginx 配置
    sudo tee /etc/nginx/sites-available/stock-tracker << NGINXEOF
server {
    listen 80;
    server_name ${DOMAIN};

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;

        # WebSocket
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
NGINXEOF

    sudo ln -sf /etc/nginx/sites-available/stock-tracker /etc/nginx/sites-enabled/
    sudo rm -f /etc/nginx/sites-enabled/default
    sudo nginx -t && sudo systemctl restart nginx && sudo systemctl enable nginx
    log_info "Nginx 配置完成"

    # HTTPS 证书
    if [ -n "$EMAIL" ]; then
        log_info "申请 Let's Encrypt 证书..."
        sudo certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "$EMAIL" --redirect
        log_info "✅ HTTPS 证书配置完成"
    else
        log_warn "未设置 EMAIL，跳过 HTTPS 证书申请"
        log_info "稍后可手动运行: sudo certbot --nginx -d $DOMAIN"
    fi
}

# --------------------------------------------------------
# Step 7: 配置防火墙
# --------------------------------------------------------
setup_firewall() {
    log_step "Step 7: 配置防火墙"

    # iptables 放行
    if ! sudo iptables -L INPUT -n | grep -q "dpt:80"; then
        sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
        log_info "已放行端口 80"
    fi

    if ! sudo iptables -L INPUT -n | grep -q "dpt:443"; then
        sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
        log_info "已放行端口 443"
    fi

    # 如果没有域名配置，也放行 8000 端口直接访问
    if [ -z "$DOMAIN" ]; then
        if ! sudo iptables -L INPUT -n | grep -q "dpt:8000"; then
            sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 8000 -j ACCEPT
            log_info "已放行端口 8000（直接访问）"
        fi
    fi

    # 持久化 iptables 规则
    sudo apt-get install -y iptables-persistent
    sudo netfilter-persistent save
    log_info "防火墙规则已保存"

    log_warn "⚠️  别忘了在 Oracle Cloud 控制台的 Security List 中也添加入站规则！"
    log_warn "   需要放行: TCP 80, TCP 443${DOMAIN:+}${DOMAIN:-", TCP 8000"}"
}

# --------------------------------------------------------
# Step 8: 配置定时数据更新
# --------------------------------------------------------
setup_cron() {
    log_step "Step 8: 配置定时数据更新 (Cron)"

    # 创建容器内数据更新的 host 脚本
    CRON_SCRIPT="$PROJECT_DIR/scripts/docker_daily_update.sh"
    cat > "$CRON_SCRIPT" << 'CRONEOF'
#!/bin/bash
# Docker 版每日数据更新脚本 (在宿主机通过 cron 调用)
set -euo pipefail

PROJECT_DIR="/opt/stock-tracker"
cd "$PROJECT_DIR"

LOG_FILE="logs/daily_update_$(date +%Y%m%d).log"
mkdir -p logs

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

log "========================================"
log "Docker 每日数据更新开始"
log "========================================"

EXEC="sudo docker compose exec -T web"

log "[1/5] 拉取价格数据..."
$EXEC python scripts/save_prices_yfinance.py --mode all >> "$LOG_FILE" 2>&1 && log "[1/5] ✅ 完成" || log "[1/5] ⚠️ 失败"

log "[2/5] Market Pulse..."
$EXEC python scripts/market_pulse.py --cron >> "$LOG_FILE" 2>&1 && log "[2/5] ✅ 完成" || log "[2/5] ⚠️ 失败"

log "[3/5] Stage 2 Monitor..."
$EXEC python scripts/stage2_monitor.py --cron >> "$LOG_FILE" 2>&1 && log "[3/5] ✅ 完成" || log "[3/5] ⚠️ 失败"

log "[4/5] VCP Scanner..."
$EXEC python scripts/vcp_scanner.py --cron >> "$LOG_FILE" 2>&1 && log "[4/5] ✅ 完成" || log "[4/5] ⚠️ 失败"

log "[5/5] Bottom Fisher..."
$EXEC python scripts/bottom_fisher.py --cron >> "$LOG_FILE" 2>&1 && log "[5/5] ✅ 完成" || log "[5/5] ⚠️ 失败"

log "========================================"
log "每日更新完成！"
log "========================================"

# 清理 30 天前的日志
find "$PROJECT_DIR/logs" -name "daily_update_*.log" -mtime +30 -delete 2>/dev/null || true
CRONEOF
    chmod +x "$CRON_SCRIPT"

    # 添加 cron 任务
    CRON_LINE="${CRON_MINUTE} ${CRON_HOUR} * * 1-5 ${CRON_SCRIPT}"
    ( crontab -l 2>/dev/null | grep -v "docker_daily_update.sh"; echo "$CRON_LINE" ) | crontab -
    log_info "Cron 任务已设置: 每个交易日 UTC ${CRON_HOUR}:$(printf '%02d' "$CRON_MINUTE") 执行数据更新"
}

# --------------------------------------------------------
# 显示状态
# --------------------------------------------------------
show_status() {
    log_step "部署状态"
    cd "$PROJECT_DIR"

    echo ""
    echo "📦 Docker 容器:"
    sudo docker compose ps
    echo ""
    echo "💾 数据卷:"
    sudo docker volume ls | grep stock || echo "  (无)"
    echo ""
    echo "🔄 Cron 定时任务:"
    crontab -l 2>/dev/null | grep "docker_daily_update" || echo "  (无)"
    echo ""

    if [ -n "${DOMAIN:-}" ]; then
        echo "🌐 访问地址: https://$DOMAIN"
    else
        PUBLIC_IP=$(curl -s ifconfig.me 2>/dev/null || echo "<公网IP>")
        echo "🌐 访问地址: http://${PUBLIC_IP}:8000"
    fi
    echo ""
}

# --------------------------------------------------------
# 主逻辑
# --------------------------------------------------------
main() {
    case "${1:-}" in
        --update)
            log_step "🔄 更新部署"
            check_sudo
            setup_code
            build_image
            start_container
            show_status
            log_info "✅ 更新完成！"
            ;;
        --restart)
            log_step "🔄 重启服务"
            cd "$PROJECT_DIR"
            sudo docker compose restart
            show_status
            ;;
        --status)
            show_status
            ;;
        --init-data)
            log_step "📊 初始化数据"
            check_sudo
            init_data
            ;;
        "")
            log_step "🚀 Stock Tracker — Oracle Cloud Docker 全新部署"
            echo ""
            echo "部署将执行以下步骤:"
            echo "  1. 安装 Docker"
            echo "  2. 拉取代码"
            echo "  3. 构建 Docker 镜像"
            echo "  4. 启动容器"
            echo "  5. 初始化数据库 & 数据"
            echo "  6. 配置 Nginx + HTTPS"
            echo "  7. 配置防火墙"
            echo "  8. 设置定时数据更新"
            echo ""
            read -rp "确认开始? [Y/n] " confirm
            if [[ "${confirm:-Y}" =~ ^[Nn] ]]; then
                echo "已取消"
                exit 0
            fi
            echo ""

            check_sudo
            install_docker
            setup_code
            build_image
            start_container
            init_data
            setup_nginx
            setup_firewall
            setup_cron
            show_status

            echo ""
            log_info "🎉 部署全部完成！"
            echo ""
            if [ -n "$DOMAIN" ]; then
                echo "  访问: https://$DOMAIN"
            else
                PUBLIC_IP=$(curl -s ifconfig.me 2>/dev/null || echo "<公网IP>")
                echo "  访问: http://${PUBLIC_IP}:8000"
            fi
            echo ""
            echo "  常用命令:"
            echo "    sudo docker compose logs -f         # 查看实时日志"
            echo "    sudo docker compose restart          # 重启服务"
            echo "    bash scripts/deploy_docker.sh --update   # 更新部署"
            echo "    bash scripts/deploy_docker.sh --status   # 查看状态"
            echo ""
            ;;
        *)
            echo "用法: bash scripts/deploy_docker.sh [选项]"
            echo ""
            echo "选项:"
            echo "  (无参数)      首次全新部署"
            echo "  --update      更新代码并重新部署"
            echo "  --restart     重启容器"
            echo "  --status      查看部署状态"
            echo "  --init-data   仅初始化/重置数据"
            echo ""
            ;;
    esac
}

main "$@"
