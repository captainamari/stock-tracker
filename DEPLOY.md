# 🚀 Stock Tracker Web 部署指南

## 目录

- [一、Windows 本地运行](#一windows-本地运行)
- [二、Linux 服务器部署（Oracle Cloud）](#二linux-服务器部署oracle-cloud)
  - [Step 1: 服务器基础环境](#step-1-服务器基础环境)
  - [Step 2: 拉取代码](#step-2-拉取代码)
  - [Step 3: Python 环境](#step-3-python-环境)
  - [Step 4: 初始化数据库 & 数据](#step-4-初始化数据库--数据)
  - [Step 5: 测试启动](#step-5-测试启动)
  - [Step 6: Systemd 守护进程](#step-6-systemd-守护进程)
  - [Step 7: Nginx 反向代理](#step-7-nginx-反向代理)
  - [Step 8: 域名解析](#step-8-域名解析)
  - [Step 9: HTTPS 证书（Let's Encrypt）](#step-9-https-证书lets-encrypt)
  - [Step 10: Oracle Cloud 防火墙](#step-10-oracle-cloud-防火墙)
  - [Step 11: 定时数据更新（Cron）](#step-11-定时数据更新cron)
- [三、Docker 部署（Oracle Cloud）](#三docker-部署oracle-cloud)
  - [方式 A: 一键部署脚本](#方式-a-一键部署脚本)
  - [方式 B: 手动分步部署](#方式-b-手动分步部署)
  - [Docker 日常运维](#docker-日常运维)
- [四、日常运维](#四日常运维)
- [五、故障排查](#五故障排查)

---

## 一、Windows 本地运行

### 1. 安装 Python

确保已安装 Python 3.10+，下载地址：https://www.python.org/downloads/

```powershell
# 验证 Python 版本
python --version
```

### 2. 安装依赖

```powershell
cd D:\eh\projects\stock-tracker

# （推荐）创建虚拟环境
python -m venv venv
.\venv\Scripts\Activate.ps1

# 安装依赖
pip install -r requirements.txt
```

### 3. 初始化数据库

```powershell
python -m lib.db init
```

### 4. 启动 Web 服务

```powershell
# 方式一：直接启动（推荐开发调试）
python -m web.app

# 方式二：使用 uvicorn（支持热重载）
uvicorn web.app:app --reload --port 8000
```

### 5. 访问

打开浏览器访问：**http://127.0.0.1:8000**

| 页面 | 地址 |
|------|------|
| Dashboard | http://127.0.0.1:8000/ |
| Watchlist | http://127.0.0.1:8000/watchlist |
| Ticker Detail | http://127.0.0.1:8000/ticker/AAPL |

---

## 二、Linux 服务器部署（Oracle Cloud）

> 以下步骤基于 **Ubuntu 22.04/24.04**（Oracle Cloud 免费 ARM 实例推荐系统）。
> 如使用 Oracle Linux / CentOS，将 `apt` 替换为 `dnf`。

### Step 1: 服务器基础环境

SSH 登录到 Oracle Cloud 实例：

```bash
ssh -i <你的私钥路径> ubuntu@<你的公网IP>
```

更新系统 & 安装基础工具：

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git python3 python3-pip python3-venv nginx certbot python3-certbot-nginx ufw
```

### Step 2: 拉取代码

```bash
# 创建项目目录
sudo mkdir -p /home/opc/stock-tracker
sudo chown $USER:$USER /home/opc/stock-tracker

# 克隆代码（替换为你的实际仓库地址）
git clone https://github.com/<你的用户名>/stock-tracker.git /home/opc/stock-tracker

# 进入项目目录
cd /home/opc/stock-tracker
```

> **💡 如果是私有仓库**，需要先配置 SSH Key 或使用 Personal Access Token：
> ```bash
> # SSH 方式
> git clone git@github.com:<你的用户名>/stock-tracker.git /home/opc/stock-tracker
> 
> # Token 方式
> git clone https://<TOKEN>@github.com/<你的用户名>/stock-tracker.git /home/opc/stock-tracker
> ```

### Step 3: Python 环境

```bash
cd /home/opc/stock-tracker

# 创建虚拟环境
python3 -m venv venv

# 激活虚拟环境
source venv/bin/activate

# 安装依赖
pip install --upgrade pip
pip install -r requirements.txt
```

### Step 4: 初始化数据库 & 数据

```bash
# 确保虚拟环境已激活
source /home/opc/stock-tracker/venv/bin/activate
cd /home/opc/stock-tracker

# 初始化数据库 Schema
python -m lib.db init

# 同步观察列表
python lib/config.py

# 首次拉取价格数据（耗时较长，需要从 Yahoo Finance 下载）
python scripts/save_prices_yfinance.py

# 运行全部策略生成初始数据
python scripts/market_pulse.py
python scripts/stage2_monitor.py
python scripts/vcp_scanner.py
python scripts/bottom_fisher.py
```

> **⚠️ 注意**：`.gitignore` 中排除了 `*.db` 文件，所以数据库不会随代码推送。
> 每次部署需要在服务器上重新初始化数据库并拉取数据。
>
> **可选方案**：你也可以从 Windows 手动上传 `data/stock_tracker.db` 到服务器：
> ```bash
> # 在 Windows 本地执行（用 scp 上传数据库）
> scp -i <私钥> D:\eh\projects\stock-tracker\data\stock_tracker.db ubuntu@<公网IP>:/home/opc/stock-tracker/data/
> ```

### Step 5: 测试启动

先手动测试确认能正常运行：

```bash
cd /home/opc/stock-tracker
source venv/bin/activate

# 测试启动（监听 0.0.0.0 以便外部访问）
uvicorn web.app:app --host 0.0.0.0 --port 8000

# 看到以下输出说明成功：
# INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

在本地浏览器访问 `http://<你的公网IP>:8000` 测试（需要先开放 8000 端口，见 Step 10）。

确认正常后 `Ctrl+C` 停止。

### Step 6: Systemd 守护进程

创建 systemd 服务文件，让 Web 服务开机自启、崩溃自动重启：

```bash
sudo tee /etc/systemd/system/stock-tracker.service << 'EOF'
[Unit]
Description=Stock Tracker Web Dashboard
After=network.target

[Service]
Type=simple
User=ubuntu
Group=ubuntu
WorkingDirectory=/home/opc/stock-tracker
Environment="PATH=/home/opc/stock-tracker/venv/bin:/usr/bin"
ExecStart=/home/opc/stock-tracker/venv/bin/uvicorn web.app:app --host 127.0.0.1 --port 8000 --workers 2
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
```

启动并设为开机自启：

```bash
# 重新加载 systemd 配置
sudo systemctl daemon-reload

# 启动服务
sudo systemctl start stock-tracker

# 设为开机自启
sudo systemctl enable stock-tracker

# 查看服务状态
sudo systemctl status stock-tracker
```

常用管理命令：

```bash
sudo systemctl start stock-tracker     # 启动
sudo systemctl stop stock-tracker      # 停止
sudo systemctl restart stock-tracker   # 重启
sudo systemctl status stock-tracker    # 查看状态
journalctl -u stock-tracker -f         # 查看实时日志
journalctl -u stock-tracker --since "1 hour ago"  # 查看最近1小时日志
```

### Step 7: Nginx 反向代理

Nginx 作为反向代理，将域名请求转发到 Uvicorn（8000 端口），并处理 SSL、静态文件缓存等。

创建 Nginx 配置文件：

```bash
sudo tee /etc/nginx/sites-available/stock-tracker << 'EOF'
server {
    listen 80;
    server_name your-domain.com;    # ← 替换为你的域名

    # 静态文件直接由 Nginx 服务（更高效）
    location /static/ {
        alias /home/opc/stock-tracker/web/static/;
        expires 7d;
        add_header Cache-Control "public, immutable";
    }

    # 所有其他请求转发给 Uvicorn
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket 支持（如果未来需要）
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
EOF
```

启用配置：

```bash
# 创建软链接启用站点
sudo ln -sf /etc/nginx/sites-available/stock-tracker /etc/nginx/sites-enabled/

# 删除默认站点（可选）
sudo rm -f /etc/nginx/sites-enabled/default

# 测试 Nginx 配置语法
sudo nginx -t

# 重启 Nginx
sudo systemctl restart nginx
sudo systemctl enable nginx
```

### Step 8: 域名解析

在你的域名服务商（如 Cloudflare、阿里云、GoDaddy 等）添加 DNS 记录：

| 类型 | 名称 | 值 | TTL |
|------|------|-----|-----|
| A | `@` 或 `stocks`（子域名） | `<你的Oracle Cloud 公网IP>` | 600 |

示例：
- 如果域名是 `example.com`，设置 A 记录 `stocks` → `129.xxx.xxx.xxx`
- 最终访问地址就是 `http://stocks.example.com`

验证 DNS 是否生效：

```bash
# 在本地或服务器上检查
nslookup stocks.example.com
# 或
dig stocks.example.com
```

### Step 9: HTTPS 证书（Let's Encrypt）

使用 Certbot 自动获取免费 SSL 证书：

```bash
# 确保 Nginx 配置中的 server_name 已改为你的实际域名
# 然后运行 Certbot
sudo certbot --nginx -d your-domain.com

# 按提示操作：
# 1. 输入邮箱（用于证书到期提醒）
# 2. 同意服务条款
# 3. 选择是否重定向 HTTP → HTTPS（推荐选 2 - Redirect）
```

Certbot 会自动修改 Nginx 配置，添加 SSL 证书路径和 HTTPS 重定向。

验证自动续期：

```bash
# 测试续期流程
sudo certbot renew --dry-run

# Certbot 会自动设置定时任务续期，无需手动操作
# 查看定时任务
sudo systemctl list-timers | grep certbot
```

完成后，访问 **https://your-domain.com** 应该能看到 Dashboard。

### Step 10: Oracle Cloud 防火墙

Oracle Cloud 有**两层防火墙**，都需要配置：

#### 10a. 操作系统防火墙 (iptables)

Oracle Cloud 的 Ubuntu 镜像默认使用 `iptables`（不是 `ufw`），需要手动放行：

```bash
# 放行 HTTP (80) 和 HTTPS (443)
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT

# 持久化规则（重启后不丢失）
sudo apt install -y iptables-persistent
sudo netfilter-persistent save
```

> **如果你使用 `ufw`**（需要先禁用 iptables 默认规则）：
> ```bash
> sudo ufw allow 22/tcp    # SSH（必须！否则会被锁在外面）
> sudo ufw allow 80/tcp    # HTTP
> sudo ufw allow 443/tcp   # HTTPS
> sudo ufw enable
> ```

#### 10b. Oracle Cloud 安全列表（Security List / NSG）

这一步**必须**在 Oracle Cloud 控制台操作，否则即使服务器端口开了，外部也无法访问：

1. 登录 [Oracle Cloud Console](https://cloud.oracle.com/)
2. 进入 **Networking** → **Virtual Cloud Networks**
3. 点击你的 VCN → **Subnets** → 点击实例所在的子网
4. 点击 **Security Lists** → 选择默认安全列表
5. 点击 **Add Ingress Rules**，添加以下规则：

| Source CIDR | Protocol | Dest Port | Description |
|-------------|----------|-----------|-------------|
| `0.0.0.0/0` | TCP | 80 | HTTP |
| `0.0.0.0/0` | TCP | 443 | HTTPS |

6. 保存规则

### Step 11: 定时数据更新（Cron）

设置定时任务，每天自动拉取数据并运行策略：

```bash
# 创建数据更新脚本
sudo tee /home/opc/stock-tracker/scripts/daily_update.sh << 'SCRIPT'
#!/bin/bash
# Stock Tracker 每日数据更新脚本
# 建议在美股收盘后运行（美东时间 16:30 之后）

set -e
cd /home/opc/stock-tracker
source venv/bin/activate

LOG_FILE="logs/daily_update_$(date +%Y%m%d).log"
mkdir -p logs

echo "========================================" >> "$LOG_FILE"
echo "开始更新: $(date)" >> "$LOG_FILE"
echo "========================================" >> "$LOG_FILE"

# Step 1: 拉取价格数据
echo "[1/5] 拉取价格数据..." >> "$LOG_FILE"
python scripts/save_prices_yfinance.py --mode all >> "$LOG_FILE" 2>&1

# Step 2: 运行策略
echo "[2/5] Market Pulse..." >> "$LOG_FILE"
python scripts/market_pulse.py --cron >> "$LOG_FILE" 2>&1

echo "[3/5] Stage 2 Monitor..." >> "$LOG_FILE"
python scripts/stage2_monitor.py --cron >> "$LOG_FILE" 2>&1

echo "[4/5] VCP Scanner..." >> "$LOG_FILE"
python scripts/vcp_scanner.py --cron >> "$LOG_FILE" 2>&1

echo "[5/5] Bottom Fisher..." >> "$LOG_FILE"
python scripts/bottom_fisher.py --cron >> "$LOG_FILE" 2>&1

echo "========================================" >> "$LOG_FILE"
echo "更新完成: $(date)" >> "$LOG_FILE"
echo "========================================" >> "$LOG_FILE"

# 清理 30 天前的日志
find /home/opc/stock-tracker/logs -name "daily_update_*.log" -mtime +30 -delete
SCRIPT

# 赋予执行权限
chmod +x /home/opc/stock-tracker/scripts/daily_update.sh
```

添加 Cron 定时任务：

```bash
# 编辑 crontab
crontab -e

# 添加以下行（每天 UTC 05:00 = 美东时间 01:00 = 北京时间 13:00 执行）
# 你可以根据需要调整时间
0 5 * * 1-5 /home/opc/stock-tracker/scripts/daily_update.sh

# 说明：
# 0 5    = UTC 时间 05:00
# * *    = 每月每天
# 1-5    = 周一到周五（美股交易日）
```

> **💡 时间选择建议**：
> - 美股收盘时间：美东 16:00 = UTC 20:00 / 21:00（夏/冬令时）
> - 建议至少等收盘后 30 分钟再拉取数据
> - 如果你在北京时间，美股收盘大约是 北京时间 04:00-05:00
> - 所以设置 cron 在 UTC 21:30 (约北京时间 05:30) 比较合适：
>   `30 21 * * 1-5 /home/opc/stock-tracker/scripts/daily_update.sh`

---

## 三、Docker 部署（Oracle Cloud）

### 选择部署脚本

根据你的 Oracle Cloud 实例系统镜像选择对应脚本：

| 系统镜像 | 部署脚本 | 包管理器 | 防火墙 |
|----------|---------|---------|--------|
| **Ubuntu 22.04/24.04** | `scripts/deploy_docker.sh` | apt | iptables |
| **Oracle Linux 8.x** (如 `Oracle-Linux-8.6-aarch64`) | `scripts/deploy_docker_ol8.sh` | dnf | firewalld |

> **💡 如何确认系统？** SSH 登录后执行 `cat /etc/os-release`

### 项目已包含的 Docker 文件

| 文件 | 说明 |
|------|------|
| `Dockerfile` | 多阶段构建，生成轻量运行镜像（兼容 ARM64 & x86_64） |
| `docker-compose.yml` | 定义服务、端口映射、数据卷持久化 |
| `.dockerignore` | 排除不需要的文件，减小镜像体积 |
| `scripts/deploy_docker.sh` | 一键部署脚本 — **Ubuntu** |
| `scripts/deploy_docker_ol8.sh` | 一键部署脚本 — **Oracle Linux 8** |

### 方式 A: 一键部署脚本

这是最简单的方式，脚本会自动完成所有步骤（安装 Docker、构建镜像、初始化数据、配置 Nginx + HTTPS、防火墙、Cron 定时任务）。

#### 1. SSH 登录服务器

```bash
# Ubuntu 实例默认用户是 ubuntu
ssh -i <你的私钥路径> ubuntu@<你的公网IP>

# Oracle Linux 实例默认用户是 opc
ssh -i <你的私钥路径> opc@<你的公网IP>
```

#### 2. 拉取代码

```bash
sudo mkdir -p /home/opc/stock-tracker
sudo chown $USER:$USER /home/opc/stock-tracker
git clone https://github.com/<你的用户名>/stock-tracker.git /home/opc/stock-tracker
cd /home/opc/stock-tracker
```

#### 3. 修改部署配置

编辑脚本顶部的配置变量：

```bash
# Ubuntu 系统
nano scripts/deploy_docker.sh

# Oracle Linux 8 系统
nano scripts/deploy_docker_ol8.sh
```

需要修改的变量：

```bash
DOMAIN="stocks.example.com"     # 你的域名（留空则跳过 Nginx/SSL）
EMAIL="your@email.com"          # Let's Encrypt 证书邮箱
GIT_REPO="https://github.com/<你的用户名>/stock-tracker.git"
```

#### 4. 执行部署

```bash
# Ubuntu 系统
bash scripts/deploy_docker.sh

# Oracle Linux 8 系统
bash scripts/deploy_docker_ol8.sh
```

脚本会依次执行：
1. ✅ 安装 Docker
2. ✅ 构建 Docker 镜像
3. ✅ 启动容器
4. ✅ 初始化数据库 & 拉取数据
5. ✅ 配置 Nginx 反向代理 + HTTPS
6. ✅ 配置 OS 防火墙
7. ✅ 设置 Cron 定时数据更新

> **⚠️ 别忘了**：还需要在 Oracle Cloud 控制台的 **Security List** 中放行 TCP 80 和 443 端口（参见 [Step 10](#step-10-oracle-cloud-防火墙)）。

#### 5. 后续更新

本地修改代码推送后，在服务器上一条命令即可更新：

```bash
# Ubuntu
bash scripts/deploy_docker.sh --update

# Oracle Linux 8
bash scripts/deploy_docker_ol8.sh --update
```

### 方式 B: 手动分步部署

如果你想更精细地控制每一步，可以手动执行：

#### 1. 安装 Docker

```bash
# 安装 Docker（官方脚本）
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER

# 重新登录 SSH 使 docker 组生效，或执行:
newgrp docker
```

#### 2. 拉取代码 & 构建镜像

```bash
cd /home/opc/stock-tracker

# 构建镜像
docker compose build

# 启动容器（后台运行）
docker compose up -d
```

#### 3. 初始化数据

```bash
# 初始化数据库
docker compose exec web python -m lib.db init

# 同步观察列表
docker compose exec web python lib/config.py

# 拉取价格数据
docker compose exec web python scripts/save_prices_yfinance.py --mode all

# 运行策略
docker compose exec web python scripts/market_pulse.py --cron
docker compose exec web python scripts/stage2_monitor.py --cron
docker compose exec web python scripts/vcp_scanner.py --cron
docker compose exec web python scripts/bottom_fisher.py --cron
```

#### 4. 验证

```bash
# 查看容器状态
docker compose ps

# 查看日志
docker compose logs -f

# 测试访问
curl http://127.0.0.1:8000
```

> Nginx、HTTPS、防火墙的配置与[方式二（Linux 直接部署）](#step-7-nginx-反向代理)相同，此处不再重复。

#### 5. 可选：上传 Windows 本地数据库

如果你想跳过数据拉取步骤，可以从 Windows 上传已有数据库：

```bash
# 在 Windows 本地执行
scp -i <私钥> D:\eh\projects\stock-tracker\data\stock_tracker.db ubuntu@<公网IP>:/tmp/

# 在服务器上将数据库复制到 Docker 数据卷
docker compose cp /tmp/stock_tracker.db web:/app/data/stock_tracker.db
```

### Docker 日常运维

```bash
cd /home/opc/stock-tracker

# ---------- 容器管理 ----------
docker compose up -d              # 启动
docker compose down                # 停止并移除容器
docker compose restart             # 重启
docker compose ps                  # 查看状态
docker compose logs -f             # 实时日志
docker compose logs --tail=100     # 最近 100 行日志

# ---------- 更新部署 ----------
git pull origin main               # 拉取最新代码
docker compose up -d --build       # 重新构建并启动

# 或使用一键脚本:
bash scripts/deploy_docker.sh --update

# ---------- 数据库操作 ----------
# 进入容器
docker compose exec web bash

# 在容器内执行命令
docker compose exec web python -m lib.db stats

# 备份数据库（从数据卷复制到宿主机）
docker compose cp web:/app/data/stock_tracker.db ./backup_$(date +%Y%m%d).db

# ---------- 手动触发数据更新 ----------
bash scripts/docker_daily_update.sh

# ---------- 查看部署状态 ----------
bash scripts/deploy_docker.sh --status
```

---

## 四、日常运维

### 代码更新

当你在本地修改代码并推送后，在服务器上更新：

```bash
cd /home/opc/stock-tracker

# 拉取最新代码
git pull origin main

# 如果依赖有变化
source venv/bin/activate
pip install -r requirements.txt

# 重启服务
sudo systemctl restart stock-tracker
```

### 查看日志

```bash
# Web 服务日志（实时跟踪）
journalctl -u stock-tracker -f

# 数据更新日志
cat /home/opc/stock-tracker/logs/daily_update_$(date +%Y%m%d).log

# Nginx 访问日志
sudo tail -f /var/log/nginx/access.log

# Nginx 错误日志
sudo tail -f /var/log/nginx/error.log
```

### 手动触发数据更新

```bash
cd /home/opc/stock-tracker
source venv/bin/activate
bash scripts/daily_update.sh
```

### 数据库备份

```bash
# 手动备份
cp /home/opc/stock-tracker/data/stock_tracker.db /home/opc/stock-tracker/data/stock_tracker_backup_$(date +%Y%m%d).db

# 设置自动备份（每周日凌晨备份，保留4周）
crontab -e
# 添加：
0 4 * * 0 cp /home/opc/stock-tracker/data/stock_tracker.db /home/opc/stock-tracker/data/backup_$(date +\%Y\%m\%d).db && find /home/opc/stock-tracker/data -name "backup_*.db" -mtime +28 -delete
```

---

## 五、故障排查

### 常见问题

#### 1. 服务启动失败

```bash
# 查看详细错误
sudo systemctl status stock-tracker
journalctl -u stock-tracker --no-pager -n 50

# 手动测试启动（看完整报错）
cd /home/opc/stock-tracker
source venv/bin/activate
uvicorn web.app:app --host 127.0.0.1 --port 8000
```

#### 2. 域名无法访问

逐层排查：

```bash
# 1. 确认 Uvicorn 在运行
curl http://127.0.0.1:8000
# 应该返回 HTML 内容

# 2. 确认 Nginx 在运行
sudo systemctl status nginx

# 3. 确认 Nginx 配置正确
sudo nginx -t

# 4. 确认端口开放
sudo ss -tlnp | grep -E ':80|:443'

# 5. 确认 OS 防火墙
sudo iptables -L INPUT -n --line-numbers | grep -E '80|443'

# 6. 如果以上都正常，检查 Oracle Cloud 安全列表是否放行了 80/443
```

#### 3. 数据库为空 / 页面没数据

```bash
cd /home/opc/stock-tracker
source venv/bin/activate

# 检查数据库状态
python -m lib.db stats

# 如果为空，重新初始化并拉取数据
python -m lib.db init
python lib/config.py
python scripts/save_prices_yfinance.py
python scripts/market_pulse.py
python scripts/stage2_monitor.py
python scripts/vcp_scanner.py
python scripts/bottom_fisher.py
```

#### 4. Certbot 证书续期失败

```bash
# 手动续期
sudo certbot renew

# 如果失败，检查 Nginx 配置
sudo nginx -t
sudo systemctl restart nginx
sudo certbot renew
```

#### 5. yfinance 拉取数据超时/被限流

```bash
# Oracle Cloud 日本区/韩国区 IP 可能被 Yahoo Finance 限流
# 可以尝试加代理或减少请求频率
# 查看拉取日志
cat /home/opc/stock-tracker/logs/daily_update_$(date +%Y%m%d).log | tail -50
```

---

## 快速参考卡片

```
📍 项目路径:    /home/opc/stock-tracker
📍 虚拟环境:    /home/opc/stock-tracker/venv
📍 数据库:      /home/opc/stock-tracker/data/stock_tracker.db
📍 Web 服务:    systemctl {start|stop|restart|status} stock-tracker
📍 Nginx:       systemctl {start|stop|restart} nginx
📍 Nginx 配置:  /etc/nginx/sites-available/stock-tracker
📍 服务配置:    /etc/systemd/system/stock-tracker.service
📍 更新脚本:    /home/opc/stock-tracker/scripts/daily_update.sh
📍 日志:        journalctl -u stock-tracker -f
📍 数据更新日志: /home/opc/stock-tracker/logs/daily_update_YYYYMMDD.log
```
