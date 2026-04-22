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
EMAIL=""                         # 用于 Let's Encrypt 证书申请的邮箱（留空则使用 --register-unsafely-without-email）
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
# 通用工具: 带重试的命令执行
# --------------------------------------------------------
retry_cmd() {
    local max_retries="${1}"
    local delay="${2}"
    local description="${3}"
    shift 3
    local attempt=1
    while [ "$attempt" -le "$max_retries" ]; do
        if "$@"; then
            return 0
        fi
        if [ "$attempt" -lt "$max_retries" ]; then
            log_warn "${description} 失败 (第 ${attempt}/${max_retries} 次)，${delay}s 后重试..."
            sleep "$delay"
        fi
        attempt=$((attempt + 1))
    done
    log_error "${description} 在 ${max_retries} 次尝试后仍然失败"
    return 1
}

# --------------------------------------------------------
# 前置检查
# --------------------------------------------------------
preflight_check() {
    log_step "前置检查"

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

    # 检查磁盘空间（Docker 镜像构建需要空间）
    local avail_kb
    avail_kb=$(df --output=avail / | tail -1 | tr -d ' ')
    local avail_gb=$((avail_kb / 1024 / 1024))
    if [ "$avail_gb" -lt 2 ]; then
        log_error "根分区可用空间不足 2GB（当前 ${avail_gb}GB），可能导致构建失败"
        exit 1
    fi
    log_info "磁盘可用空间: ${avail_gb}GB ✅"

    # 检查内存
    local mem_mb
    mem_mb=$(free -m | awk '/^Mem:/{print $7}')
    if [ "$mem_mb" -lt 256 ]; then
        log_warn "可用内存较低（${mem_mb}MB），构建过程可能较慢"
    else
        log_info "可用内存: ${mem_mb}MB ✅"
    fi

    log_info "前置检查通过"
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

        # 安装 Docker Engine（带重试，网络不稳时可能失败）
        retry_cmd 3 10 "安装 Docker 包" sudo dnf install -y docker-engine docker-cli

        # 验证安装
        if ! command -v docker &>/dev/null; then
            log_error "Docker 安装失败，请检查 dnf 源配置"
            exit 1
        fi
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
        retry_cmd 3 10 "下载 Docker Compose" \
            sudo curl -fSL "https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-${COMPOSE_ARCH}" \
                -o /usr/local/lib/docker/cli-plugins/docker-compose
        sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

        # 验证安装
        if ! docker compose version &>/dev/null; then
            log_error "Docker Compose 安装失败"
            exit 1
        fi
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

    # 验证 Docker 守护进程真正在运行
    if ! sudo docker info &>/dev/null; then
        log_error "Docker 服务启动失败，请检查: sudo journalctl -u docker --no-pager -n 30"
        exit 1
    fi
    log_info "Docker 服务已启动并设为开机自启 ✅"
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
            # GIT_REPO 为空时：检查代码是否已手动放到了目录中
            if [ -f "$PROJECT_DIR/docker-compose.yml" ]; then
                log_info "GIT_REPO 未设置，但检测到 $PROJECT_DIR 中已有项目文件，继续部署"
            else
                log_error "GIT_REPO 未设置！请修改脚本顶部的 GIT_REPO 变量"
                log_info "或者手动将代码放到 $PROJECT_DIR 目录下"
                exit 1
            fi
        else
            log_info "克隆仓库: $GIT_REPO"
            sudo mkdir -p "$(dirname "$PROJECT_DIR")"
            sudo mkdir -p "$PROJECT_DIR"
            sudo chown "$USER:$USER" "$PROJECT_DIR"
            retry_cmd 3 10 "克隆 Git 仓库" \
                git clone -b "$GIT_BRANCH" "$GIT_REPO" "$PROJECT_DIR"
        fi
    fi

    cd "$PROJECT_DIR"

    # 验证关键文件存在
    local missing_files=()
    for f in docker-compose.yml Dockerfile requirements.txt; do
        if [ ! -f "$PROJECT_DIR/$f" ]; then
            missing_files+=("$f")
        fi
    done
    if [ ${#missing_files[@]} -gt 0 ]; then
        log_error "项目缺少关键文件: ${missing_files[*]}"
        exit 1
    fi

    log_info "代码准备完毕: $PROJECT_DIR ✅"
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

        # 如果有域名(将配置 Nginx)，提前设置 httpd_can_network_connect
        # （从 Q4/Q6 排查经验：此设置必须在 Nginx 启动前完成）
        if [ -n "$DOMAIN" ]; then
            log_info "预配置 httpd_can_network_connect (Nginx 反向代理所需)..."
            sudo setsebool -P httpd_can_network_connect 1 2>/dev/null || true
        fi

        # 验证 SELinux 布尔值
        local sebool_ok=true
        if ! getsebool container_connect_any 2>/dev/null | grep -q "on"; then
            log_warn "container_connect_any 设置可能未生效"
            sebool_ok=false
        fi
        if [ -n "$DOMAIN" ] && ! getsebool httpd_can_network_connect 2>/dev/null | grep -q "on"; then
            log_warn "httpd_can_network_connect 设置可能未生效"
            sebool_ok=false
        fi

        if [ "$sebool_ok" = true ]; then
            log_info "SELinux 配置完成 ✅"
        else
            log_warn "SELinux 部分设置可能未生效，如遇问题可临时执行: sudo setenforce 0"
        fi
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
    if ! sudo docker compose build --no-cache; then
        log_error "Docker 镜像构建失败！"
        log_info "常见原因: 磁盘空间不足、网络不通（无法拉取基础镜像 / pip 包）"
        log_info "排查命令:"
        log_info "  df -h /                                     # 检查磁盘"
        log_info "  sudo docker compose build --no-cache 2>&1   # 重试查看详细日志"
        exit 1
    fi

    # 验证镜像已创建
    if ! sudo docker images | grep -q "stock-tracker"; then
        log_error "镜像构建后未找到 stock-tracker 镜像"
        exit 1
    fi
    log_info "镜像构建完成 ✅"
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
    if ! sudo docker compose up -d; then
        log_error "容器启动失败！"
        log_info "排查命令: sudo docker compose logs --tail=50"
        exit 1
    fi
    log_info "容器已启动"

    # 等待健康检查通过
    log_info "等待服务就绪（最多 60s）..."
    local ready=false
    for i in $(seq 1 30); do
        # 先检查容器是否还活着
        if ! sudo docker compose ps --status running | grep -q "web"; then
            log_error "容器意外退出！查看日志:"
            sudo docker compose logs --tail=30
            exit 1
        fi
        # 检查服务响应
        if sudo docker compose exec -T web python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/')" 2>/dev/null; then
            ready=true
            log_info "✅ Web 服务已就绪!"
            break
        fi
        sleep 2
    done

    if [ "$ready" = false ]; then
        log_warn "服务启动超时（60s），但容器仍在运行中"
        log_info "容器状态:"
        sudo docker compose ps
        log_info "最近日志:"
        sudo docker compose logs --tail=20
        log_info "请稍后手动验证: curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/"
    fi

    # 额外验证: 从宿主机直接 curl
    if command -v curl &>/dev/null; then
        local http_code
        http_code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:8000/ 2>/dev/null || echo "000")
        if [ "$http_code" = "200" ]; then
            log_info "宿主机 curl 验证: HTTP $http_code ✅"
        else
            log_warn "宿主机 curl 验证: HTTP $http_code（可能服务仍在启动中）"
        fi
    fi
}

# --------------------------------------------------------
# Step 6: 初始化数据库 & 数据
# --------------------------------------------------------
init_data() {
    log_step "Step 6: 初始化数据库 & 数据"
    cd "$PROJECT_DIR"

    local step_failed=false

    log_info "[1/3] 初始化数据库 Schema..."
    if ! sudo docker compose exec -T web python -m lib.db init; then
        log_warn "[1/3] 数据库 Schema 初始化失败（可能已存在）"
        step_failed=true
    fi

    log_info "[2/3] 同步观察列表..."
    if ! sudo docker compose exec -T web python -m lib.config; then
        log_warn "[2/3] 同步观察列表失败"
        step_failed=true
    fi

    log_info "[3/3] 运行 Daily Pipeline（数据采集 + 策略计算，跳过推送）..."
    log_info "      包含: 价格拉取 → Market Pulse → Stage 2 → VCP → Bottom Fisher → Buying Checklist"
    if ! sudo docker compose exec -T web python scripts/daily_pipeline.py --force --no-notify; then
        log_warn "[3/3] Pipeline 部分步骤失败（非致命，可稍后重试）"
        step_failed=true
    fi

    if [ "$step_failed" = true ]; then
        log_warn "部分数据初始化步骤失败，服务仍可运行。可稍后执行:"
        log_info "  bash scripts/deploy_docker_ol8.sh --init-data"
        log_info "  或单独重试推送: sudo docker compose exec -T web python scripts/daily_pipeline.py --notify-only"
    else
        log_info "✅ 数据初始化完成"
    fi
}

# --------------------------------------------------------
# Step 7: 配置防火墙 (firewalld)
# ————————————————————————————————
# ⚠️ 从排查经验得知: 防火墙必须在 Nginx/certbot
#    之前配置好，否则 certbot 的 HTTP-01 验证因 80 端口不通而失败
# --------------------------------------------------------
setup_firewall() {
    log_step "Step 7: 配置防火墙 (firewalld)"

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

    # 如果没有域名，额外放行 8000 端口以便直接访问
    if [ -z "$DOMAIN" ]; then
        sudo firewall-cmd --permanent --add-port=8000/tcp
        log_info "已放行端口 8000（直接访问）"
    fi

    # 重载防火墙使规则生效
    sudo firewall-cmd --reload
    log_info "防火墙规则已生效"

    # 验证放行结果（从 Q7 排查经验）
    local fw_services
    fw_services=$(sudo firewall-cmd --list-services 2>/dev/null || echo "")
    if echo "$fw_services" | grep -q "http" && echo "$fw_services" | grep -q "https"; then
        log_info "验证: HTTP 和 HTTPS 已在放行列表中 ✅"
    else
        log_error "验证失败: 防火墙规则可能未正确生效！"
        log_info "当前服务列表: $fw_services"
        log_info "手动修复: sudo firewall-cmd --permanent --add-service={http,https} && sudo firewall-cmd --reload"
    fi

    # 显示当前规则
    log_info "当前放行的服务和端口:"
    sudo firewall-cmd --list-all

    echo ""
    log_warn "⚠️  别忘了在 Oracle Cloud 控制台的 Security List 中也添加入站规则！"
    log_warn "   Networking → VCN → Subnets → Security Lists → Add Ingress Rules"
    log_warn "   需要放行: TCP 80, TCP 443${DOMAIN:+}${DOMAIN:-", TCP 8000"}"
}

# --------------------------------------------------------
# Step 8: 安装 Nginx 反向代理 + HTTPS
# ————————————————————————————————
# ⚠️ 从排查经验得知:
#    - 必须在防火墙放行 80/443 之后再执行（certbot HTTP-01 验证需要 80 端口从外部可达）
#    - SELinux httpd_can_network_connect 必须提前设置
#    - EMAIL 为空时应使用 --register-unsafely-without-email，而非跳过 certbot
# --------------------------------------------------------
setup_nginx() {
    if [ -z "$DOMAIN" ]; then
        log_warn "未设置域名 (DOMAIN)，跳过 Nginx/SSL 配置"
        log_info "你可以直接通过 http://<服务器IP>:8000 访问"
        return
    fi

    log_step "Step 8: 配置 Nginx 反向代理"

    # 安装 Nginx
    if ! rpm -q nginx &>/dev/null; then
        sudo dnf install -y nginx
    else
        log_info "Nginx 已安装: $(nginx -v 2>&1)"
    fi

    # 备份已有配置（避免重复部署覆盖 certbot 修改后的配置）
    if [ -f /etc/nginx/conf.d/stock-tracker.conf ]; then
        sudo cp /etc/nginx/conf.d/stock-tracker.conf "/etc/nginx/conf.d/stock-tracker.conf.bak.$(date +%s)"
        log_info "已备份现有 Nginx 配置"
    fi

    # 移除可能冲突的默认 server 块（Oracle Linux 8 默认有 /etc/nginx/nginx.conf 中的 server）
    # 只在首次配置时处理
    if grep -q "listen.*80.*default_server" /etc/nginx/nginx.conf 2>/dev/null; then
        log_info "注释掉 nginx.conf 中的默认 server 块以避免冲突..."
        sudo sed -i '/^\s*server\s*{/,/^\s*}/s/^/#DISABLED_BY_DEPLOY# /' /etc/nginx/nginx.conf 2>/dev/null || true
    fi

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

    # SELinux: 确保 Nginx 可以做反向代理连接（Step 3 可能已设置，这里再次确认）
    sudo setsebool -P httpd_can_network_connect 1 2>/dev/null || true

    # 验证 Nginx 配置语法
    if ! sudo nginx -t; then
        log_error "Nginx 配置语法检查失败！"
        log_info "检查配置: sudo nginx -t"
        log_info "查看配置: cat /etc/nginx/conf.d/stock-tracker.conf"
        exit 1
    fi
    log_info "Nginx 配置语法检查通过 ✅"

    sudo systemctl restart nginx && sudo systemctl enable nginx

    # 验证 Nginx 正在监听 80 端口
    if sudo ss -tlnp | grep -q ":80 "; then
        log_info "Nginx 正在监听 80 端口 ✅"
    else
        log_warn "Nginx 似乎未在 80 端口监听，请检查: sudo ss -tlnp | grep ':80'"
    fi

    # 验证通过 Nginx 反向代理可以访问后端
    local proxy_code
    proxy_code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 -H "Host: ${DOMAIN}" http://127.0.0.1:80/ 2>/dev/null || echo "000")
    if [ "$proxy_code" = "200" ]; then
        log_info "Nginx 反向代理验证: HTTP $proxy_code ✅"
    else
        log_warn "Nginx 反向代理验证: HTTP $proxy_code（后端可能仍在启动中）"
    fi

    log_info "Nginx 配置完成"

    # ---- HTTPS 证书 — 使用 certbot ----
    log_info "安装 Certbot..."
    sudo dnf install -y epel-release || sudo dnf install -y oracle-epel-release-el8 || true
    sudo dnf install -y certbot python3-certbot-nginx

    # 检查是否已有有效证书（避免重复申请触发 Let's Encrypt 频率限制）
    if sudo test -d "/etc/letsencrypt/live/${DOMAIN}"; then
        log_info "检测到已有证书目录，检查证书有效性..."
        if sudo certbot certificates 2>/dev/null | grep -q "VALID"; then
            log_info "证书仍然有效，跳过重复申请 ✅"
            # 确保 Nginx 已配置 SSL（certbot 可能之前已修改过配置）
            sudo certbot install --nginx -d "$DOMAIN" --non-interactive 2>/dev/null || true
            return
        fi
        log_info "证书已过期或无效，重新申请..."
    fi

    # 构建 certbot 命令（从 Q8 排查经验: EMAIL 为空时不应跳过，使用 --register-unsafely-without-email）
    local certbot_cmd="sudo certbot --nginx -d $DOMAIN --non-interactive --agree-tos --redirect"
    if [ -n "$EMAIL" ]; then
        certbot_cmd="$certbot_cmd -m $EMAIL"
    else
        log_warn "未设置 EMAIL，使用 --register-unsafely-without-email 申请证书"
        certbot_cmd="$certbot_cmd --register-unsafely-without-email"
    fi

    log_info "申请 Let's Encrypt 证书..."
    if eval "$certbot_cmd"; then
        log_info "✅ HTTPS 证书配置完成"
    else
        log_warn "证书申请失败！常见原因:"
        log_warn "  1. 域名 DNS 未指向此服务器 IP"
        log_warn "  2. Oracle Cloud Security List 未放行 TCP 80"
        log_warn "  3. 防火墙 (firewalld) 未放行 HTTP"
        log_info "稍后可手动重试: sudo certbot --nginx -d $DOMAIN"
        log_info "HTTP 访问仍然可用: http://${DOMAIN}"
        # 不退出 — 证书失败不应阻断整个部署流程
        return
    fi

    # 设置自动续期定时器
    sudo systemctl enable --now certbot-renew.timer 2>/dev/null || {
        # 如果 systemd timer 不可用，用 cron
        ( sudo crontab -l 2>/dev/null | grep -v "certbot renew"; echo "0 3 * * * certbot renew --quiet" ) | sudo crontab -
        log_info "已通过 cron 设置证书自动续期"
    }

    # 验证 HTTPS 是否生效
    local https_code
    https_code=$(curl -sk -o /dev/null -w '%{http_code}' --max-time 5 "https://${DOMAIN}/" 2>/dev/null || echo "000")
    if [ "$https_code" = "200" ]; then
        log_info "HTTPS 验证: https://${DOMAIN} → HTTP $https_code ✅"
    else
        log_warn "HTTPS 验证: HTTP $https_code（证书可能需要几秒生效，或 443 端口未放行）"
    fi
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

    # 确保 crond 正在运行
    if ! systemctl is-active --quiet crond; then
        sudo systemctl start crond
        sudo systemctl enable crond
    fi

    # 创建宿主机上的数据更新脚本
    CRON_SCRIPT="$PROJECT_DIR/scripts/docker_daily_update.sh"
    cat > "$CRON_SCRIPT" << 'CRONEOF'
#!/bin/bash
# Docker 版每日数据更新脚本 (在宿主机通过 cron 调用)
# 委托给 daily_pipeline.py 三阶段 Pipeline 执行:
#   Phase 1: 数据采集（价格拉取）
#   Phase 2: 策略计算 + DB 持久化
#   Phase 3: Telegram 推送（从 DB 读取，幂等）
set -euo pipefail

PROJECT_DIR="/home/opc/stock-tracker"
cd "$PROJECT_DIR"

# 加载 .env（Telegram token 等配置）
if [ -f ".env" ]; then
    set -a
    source .env
    set +a
fi

# 检查容器是否在运行
if ! sudo docker compose ps --status running | grep -q "web"; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ⚠️ 容器未运行，尝试启动..."
    sudo docker compose up -d
    sleep 10
    if ! sudo docker compose ps --status running | grep -q "web"; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] ❌ 容器启动失败，退出"
        exit 1
    fi
fi

# 执行三阶段 Pipeline（daily_pipeline.py 内部自带日志和幂等控制）
exec sudo docker compose exec -T \
    -e TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}" \
    -e TELEGRAM_CHAT_ID="${TELEGRAM_CHAT_ID:-}" \
    web python scripts/daily_pipeline.py "$@"
CRONEOF
    chmod +x "$CRON_SCRIPT"

    # 添加 cron 任务
    CRON_LINE="${CRON_MINUTE} ${CRON_HOUR} * * 1-5 ${CRON_SCRIPT}"
    ( crontab -l 2>/dev/null | grep -v "docker_daily_update.sh"; echo "$CRON_LINE" ) | crontab -

    # 验证 cron 任务已添加
    if crontab -l 2>/dev/null | grep -q "docker_daily_update.sh"; then
        log_info "Cron 任务已设置: 每个交易日 UTC ${CRON_HOUR}:$(printf '%02d' "$CRON_MINUTE") 执行 Pipeline ✅"
        log_info "  Pipeline 包含: 数据采集 → 策略计算 → Telegram 推送"
    else
        log_warn "Cron 任务可能未添加成功，请手动检查: crontab -l"
    fi
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
    echo "🔒 HTTPS 证书:"
    if [ -n "${DOMAIN:-}" ]; then
        sudo certbot certificates 2>/dev/null | grep -E "(Certificate Name|Expiry Date|VALID)" || echo "  (未配置)"
    else
        echo "  (未配置域名)"
    fi
    echo ""
    echo "🔄 Cron 定时任务:"
    crontab -l 2>/dev/null | grep "docker_daily_update" || echo "  (无)"
    echo ""

    if [ -n "${DOMAIN:-}" ]; then
        echo "🌐 访问地址: https://$DOMAIN"
    else
        PUBLIC_IP=$(curl -s --max-time 5 ifconfig.me 2>/dev/null || echo "<公网IP>")
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
            echo "  7. 配置防火墙 (firewalld)"
            echo "  8. 配置 Nginx + HTTPS"
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
            setup_firewall       # ← 先配置防火墙放行 80/443
            setup_nginx          # ← 再配置 Nginx + certbot（需要 80 端口已通）
            setup_cron
            show_status

            echo ""
            log_info "🎉 部署全部完成！"
            echo ""
            if [ -n "$DOMAIN" ]; then
                echo "  访问: https://$DOMAIN"
            else
                PUBLIC_IP=$(curl -s --max-time 5 ifconfig.me 2>/dev/null || echo "<公网IP>")
                echo "  访问: http://${PUBLIC_IP}:8000"
            fi
            echo ""
            echo "  常用命令:"
            echo "    sudo docker compose logs -f                                                  # 查看实时日志"
            echo "    sudo docker compose restart                                                   # 重启服务"
            echo "    bash scripts/deploy_docker_ol8.sh --update                                   # 更新部署"
            echo "    bash scripts/deploy_docker_ol8.sh --status                                   # 查看状态"
            echo "    sudo docker compose exec -T web python scripts/daily_pipeline.py             # 手动执行 Pipeline"
            echo "    sudo docker compose exec -T web python scripts/daily_pipeline.py --dry-run   # 测试推送（不发送）"
            echo "    sudo docker compose exec -T web python scripts/daily_pipeline.py --test-bot  # 测试 Telegram Bot"
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
