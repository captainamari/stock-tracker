#!/bin/bash
# ============================================================
# Stock Tracker — Oracle Linux 8 (aarch64) Docker 一键部署脚本
# ============================================================
# 适用系统: Oracle Linux 8.x aarch64 (Oracle Cloud ARM 实例)
#
# 与 Ubuntu 版 (deploy_docker.sh) 的主要差异:
#   - 包管理器: dnf (非 apt)
#   - 防火墙:   firewalld (非 iptables)
#   - SELinux:  默认 enforcing，需要处理容器卷标签
#   - Nginx:    /etc/nginx/conf.d/ (非 sites-available/sites-enabled)
#   - Docker:   从 ol8_addons 仓库安装 docker-engine
#   - 默认用户: opc (非 ubuntu)
#
# 用法:
#   bash scripts/deploy_docker_ol8.sh              # 首次全新部署
#   bash scripts/deploy_docker_ol8.sh --update     # 更新代码并重新部署
#   bash scripts/deploy_docker_ol8.sh --restart    # 重启容器
#   bash scripts/deploy_docker_ol8.sh --status     # 查看部署状态
#   bash scripts/deploy_docker_ol8.sh --init-data  # 仅初始化/重置数据
# ============================================================

set -euo pipefail

# ======================== 配置区 ========================
# ⚠️ 部署前请修改以下变量
PROJECT_DIR="/home/opc/stock-tracker"
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
# 前置检查
# --------------------------------------------------------
preflight_check() {
    # 确认是 Oracle Linux 8
    if [ ! -f /etc/oracle-release ] && ! grep -qi "oracle" /etc/os-release 2>/dev/null; then
        log_warn "未检测到 Oracle Linux，此脚本专为 Oracle Linux 8 编写"
        read -rp "是否继续? [y/N] " confirm
        if [[ ! "${confirm:-N}" =~ ^[Yy] ]]; then
            exit 0
        fi
    fi

    # 确认架构
    ARCH=$(uname -m)
    log_info "系统架构: $ARCH"
    if [ "$ARCH" = "aarch64" ]; then
        log_info "检测到 ARM64 (aarch64) 架构 ✅"
    else
        log_info "检测到 $ARCH 架构（脚本兼容，继续执行）"
    fi

    # 检查 sudo 权限
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

        # Oracle Linux 8 推荐从 ol8_addons 仓库安装
        # 先确保 ol8_addons 仓库已启用
        if sudo dnf repolist --enabled | grep -q "ol8_addons"; then
            log_info "ol8_addons 仓库已启用"
        else
            log_info "启用 ol8_addons 仓库..."
            sudo dnf config-manager --enable ol8_addons || true
        fi

        # 安装 Docker Engine
        sudo dnf install -y docker-engine docker-cli
        log_info "Docker 安装完成: $(docker --version)"
    fi

    # 安装 docker-compose (v2 plugin 方式)
    if docker compose version &>/dev/null; then
        log_info "Docker Compose 已安装: $(docker compose version)"
    else
        log_info "安装 Docker Compose..."
        COMPOSE_VERSION="v2.29.2"
        COMPOSE_ARCH="linux-$(uname -m)"
        # aarch64 在 compose 发布中对应 linux-aarch64
        sudo mkdir -p /usr/local/lib/docker/cli-plugins
        sudo curl -SL "https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-${COMPOSE_ARCH}" \
            -o /usr/local/lib/docker/cli-plugins/docker-compose
        sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
        log_info "Docker Compose 安装完成: $(docker compose version)"
    fi

    # 将当前用户加入 docker 组
    if ! groups "$USER" | grep -q '\bdocker\b'; then
        sudo usermod -aG docker "$USER"
        log_warn "已将用户 $USER 加入 docker 组，首次使用可能需要重新登录 SSH"
    fi

    # 启动 Docker 服务
    sudo systemctl start docker
    sudo systemctl enable docker
    log_info "Docker 服务已启动并设为开机自启"
}

# --------------------------------------------------------
# Step 2: 拉取/更新代码
# --------------------------------------------------------
setup_code() {
    log_step "Step 2: 拉取代码"

    # 确保 git 已安装
    if ! command -v git &>/dev/null; then
        log_info "安装 git..."
        sudo dnf install -y git
    fi

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
# Step 3: 处理 SELinux
# --------------------------------------------------------
setup_selinux() {
    log_step "Step 3: 配置 SELinux"

    SELINUX_STATUS=$(getenforce 2>/dev/null || echo "Disabled")
    log_info "当前 SELinux 状态: $SELINUX_STATUS"

    if [ "$SELINUX_STATUS" = "Enforcing" ] || [ "$SELINUX_STATUS" = "Permissive" ]; then
        # 允许容器访问网络和挂载卷
        log_info "配置 SELinux 策略允许 Docker 容器正常运行..."

        # 允许 Docker 容器连接网络
        sudo setsebool -P container_connect_any 1 2>/dev/null || true

        # 给项目目录打上正确的 SELinux 标签
        # :Z 标签会在 docker-compose 的 volume mount 中自动处理
        log_info "SELinux 配置完成"
        log_info "提示: docker-compose.yml 中的卷挂载使用命名卷，不受 SELinux 影响"
    else
        log_info "SELinux 未启用，跳过配置"
    fi
}

# --------------------------------------------------------
# Step 4: 构建 Docker 镜像
# --------------------------------------------------------
build_image() {
    log_step "Step 4: 构建 Docker 镜像"
    cd "$PROJECT_DIR"

    log_info "构建镜像中（ARM64 首次构建可能需要 5-10 分钟）..."
    sudo docker compose build --no-cache
    log_info "镜像构建完成"
}

# --------------------------------------------------------
# Step 5: 启动容器
# --------------------------------------------------------
start_container() {
    log_step "Step 5: 启动容器"
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
# Step 6: 初始化数据库 & 数据
# --------------------------------------------------------
init_data() {
    log_step "Step 6: 初始化数据库 & 数据"
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
# Step 7: 安装 Nginx 反向代理 + HTTPS
# --------------------------------------------------------
setup_nginx() {
    if [ -z "$DOMAIN" ]; then
        log_warn "未设置域名 (DOMAIN)，跳过 Nginx/SSL 配置"
        log_info "你可以直接通过 http://<服务器IP>:8000 访问"
        return
    fi

    log_step "Step 7: 配置 Nginx 反向代理"

    # 安装 Nginx
    sudo dnf install -y nginx

    # Oracle Linux 8 使用 /etc/nginx/conf.d/ 目录（不是 sites-available）
    sudo tee /etc/nginx/conf.d/stock-tracker.conf << NGINXEOF
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

    # SELinux: 允许 Nginx 做反向代理连接
    sudo setsebool -P httpd_can_network_connect 1 2>/dev/null || true

    sudo nginx -t && sudo systemctl restart nginx && sudo systemctl enable nginx
    log_info "Nginx 配置完成"

    # HTTPS 证书 — 使用 certbot
    log_info "安装 Certbot..."
    sudo dnf install -y epel-release || sudo dnf install -y oracle-epel-release-el8 || true
    sudo dnf install -y certbot python3-certbot-nginx

    if [ -n "$EMAIL" ]; then
        log_info "申请 Let's Encrypt 证书..."
        sudo certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "$EMAIL" --redirect
        log_info "✅ HTTPS 证书配置完成"

        # 设置自动续期定时器
        sudo systemctl enable --now certbot-renew.timer 2>/dev/null || {
            # 如果 systemd timer 不可用，用 cron
            ( crontab -l 2>/dev/null | grep -v "certbot renew"; echo "0 3 * * * certbot renew --quiet" ) | sudo crontab -
            log_info "已通过 cron 设置证书自动续期"
        }
    else
        log_warn "未设置 EMAIL，跳过 HTTPS 证书申请"
        log_info "稍后可手动运行: sudo certbot --nginx -d $DOMAIN"
    fi
}

# --------------------------------------------------------
# Step 8: 配置防火墙 (firewalld)
# --------------------------------------------------------
setup_firewall() {
    log_step "Step 8: 配置防火墙 (firewalld)"

    # Oracle Linux 8 默认使用 firewalld
    if ! systemctl is-active --quiet firewalld; then
        log_info "firewalld 未运行，尝试启动..."
        sudo systemctl start firewalld
        sudo systemctl enable firewalld
    fi

    log_info "当前防火墙区域:"
    sudo firewall-cmd --get-active-zones

    # 放行 HTTP 和 HTTPS
    sudo firewall-cmd --permanent --add-service=http
    sudo firewall-cmd --permanent --add-service=https
    log_info "已放行 HTTP (80) 和 HTTPS (443)"

    # 如果没有域名，额外放行 8000 端口
    if [ -z "$DOMAIN" ]; then
        sudo firewall-cmd --permanent --add-port=8000/tcp
        log_info "已放行端口 8000（直接访问）"
    fi

    # 重载防火墙使规则生效
    sudo firewall-cmd --reload
    log_info "防火墙规则已生效"

    # 显示当前规则
    log_info "当前放行的服务和端口:"
    sudo firewall-cmd --list-all

    echo ""
    log_warn "⚠️  别忘了在 Oracle Cloud 控制台的 Security List 中也添加入站规则！"
    log_warn "   Networking → VCN → Subnets → Security Lists → Add Ingress Rules"
    log_warn "   需要放行: TCP 80, TCP 443${DOMAIN:+}${DOMAIN:-", TCP 8000"}"
}

# --------------------------------------------------------
# Step 9: 配置定时数据更新 (Cron)
# --------------------------------------------------------
setup_cron() {
    log_step "Step 9: 配置定时数据更新 (Cron)"

    # 确保 cronie 已安装（Oracle Linux 8 默认可能未安装）
    if ! command -v crontab &>/dev/null; then
        log_info "安装 cronie..."
        sudo dnf install -y cronie
        sudo systemctl enable --now crond
    fi

    # 创建宿主机上的数据更新脚本
    CRON_SCRIPT="$PROJECT_DIR/scripts/docker_daily_update.sh"
    cat > "$CRON_SCRIPT" << 'CRONEOF'
#!/bin/bash
# Docker 版每日数据更新脚本 (在宿主机通过 cron 调用)
# 适用于 Oracle Linux 8
set -euo pipefail

PROJECT_DIR="/home/opc/stock-tracker"
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
    echo "🖥️  系统信息:"
    echo "  OS:   $(cat /etc/oracle-release 2>/dev/null || cat /etc/os-release | grep PRETTY_NAME | cut -d= -f2)"
    echo "  Arch: $(uname -m)"
    echo "  SELinux: $(getenforce 2>/dev/null || echo 'N/A')"
    echo ""
    echo "📦 Docker 容器:"
    sudo docker compose ps
    echo ""
    echo "💾 数据卷:"
    sudo docker volume ls | grep stock || echo "  (无)"
    echo ""
    echo "🔥 防火墙 (firewalld):"
    sudo firewall-cmd --list-services --list-ports 2>/dev/null || echo "  (firewalld 未运行)"
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
            preflight_check
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
            preflight_check
            init_data
            ;;
        "")
            log_step "🚀 Stock Tracker — Oracle Linux 8 Docker 全新部署"
            echo ""
            echo "检测到系统: $(cat /etc/oracle-release 2>/dev/null || echo 'Oracle Linux 8') ($(uname -m))"
            echo ""
            echo "部署将执行以下步骤:"
            echo "  1. 安装 Docker + Docker Compose"
            echo "  2. 拉取代码"
            echo "  3. 配置 SELinux"
            echo "  4. 构建 Docker 镜像"
            echo "  5. 启动容器"
            echo "  6. 初始化数据库 & 数据"
            echo "  7. 配置 Nginx + HTTPS"
            echo "  8. 配置防火墙 (firewalld)"
            echo "  9. 设置定时数据更新"
            echo ""
            read -rp "确认开始? [Y/n] " confirm
            if [[ "${confirm:-Y}" =~ ^[Nn] ]]; then
                echo "已取消"
                exit 0
            fi
            echo ""

            preflight_check
            install_docker
            setup_code
            setup_selinux
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
            echo "    sudo docker compose logs -f                      # 查看实时日志"
            echo "    sudo docker compose restart                       # 重启服务"
            echo "    bash scripts/deploy_docker_ol8.sh --update       # 更新部署"
            echo "    bash scripts/deploy_docker_ol8.sh --status       # 查看状态"
            echo ""
            ;;
        *)
            echo "用法: bash scripts/deploy_docker_ol8.sh [选项]"
            echo ""
            echo "选项:"
            echo "  (无参数)      首次全新部署"
            echo "  --update      更新代码并重新部署"
            echo "  --restart     重启容器"
            echo "  --status      查看部署状态"
            echo "  --init-data   仅初始化/重置数据"
            echo ""
            echo "适用系统: Oracle Linux 8.x (aarch64/x86_64)"
            echo ""
            ;;
    esac
}

main "$@"
