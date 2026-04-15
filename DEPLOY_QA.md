# 🔧 Stock Tracker 部署排查 Q&A

> **排查时间**: 2026-04-15  
> **服务器**: Oracle Linux 8.6 aarch64 (Oracle Cloud ARM 实例)  
> **目标**: 通过域名正常访问服务  
> **连接方式**: `ssh -i ~/.ssh/id_rsa opc@<你的公网IP>`

---

## 目录

- [Q1: 服务器基本环境是否正常？](#q1-服务器基本环境是否正常)
- [Q2: Docker & Docker Compose 是否安装并运行？](#q2-docker--docker-compose-是否安装并运行)
- [Q3: 项目代码是否就位？](#q3-项目代码是否就位)
- [Q4: SELinux 是否正确配置？](#q4-selinux-是否正确配置)
- [Q5: Docker 容器是否正常运行？](#q5-docker-容器是否正常运行)
- [Q6: Nginx 反向代理是否配置正确？](#q6-nginx-反向代理是否配置正确)
- [Q7: 防火墙 (firewalld) 是否放行了必要端口？](#q7-防火墙-firewalld-是否放行了必要端口)
- [Q8: HTTPS 证书是否已配置？](#q8-https-证书是否已配置)
- [Q9: DNS 解析是否正确？](#q9-dns-解析是否正确)
- [Q10: 最终的外部访问验证](#q10-最终的外部访问验证)
- [排查结果总结](#排查结果总结)

---

## Q1: 服务器基本环境是否正常？

### 检查命令

```bash
cat /etc/oracle-release
uname -m
getenforce
uptime
df -h /
free -h
```

### 结论

✅ **正常** — 系统环境健康，资源充足。

---

## Q2: Docker & Docker Compose 是否安装并运行？

### 检查命令

```bash
# 版本检查
docker --version
docker compose version

# 服务状态
sudo systemctl is-active docker
sudo systemctl is-enabled docker

# 用户组
groups opc
```

### 排查结果

| 项目 | 结果 |
|------|------|
| Docker 版本 | Docker version 26.1.3 ✅ |
| Docker Compose 版本 | Docker Compose version v2.27.0 ✅ |
| Docker 服务 | active (运行中) ✅ |
| 开机自启 | enabled ✅ |
| opc 用户在 docker 组 | 是 (`opc : opc adm systemd-journal docker`) ✅ |

### 结论

✅ **正常** — Docker 和 Docker Compose 均已安装并运行。

### 如果异常，修复方法

```bash
# 安装 Docker (Oracle Linux 8)
sudo dnf config-manager --enable ol8_addons
sudo dnf install -y docker-engine docker-cli

# 安装 Docker Compose
COMPOSE_VERSION="v2.29.2"
sudo mkdir -p /usr/local/lib/docker/cli-plugins
sudo curl -SL "https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-linux-aarch64" \
    -o /usr/local/lib/docker/cli-plugins/docker-compose
sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

# 将用户加入 docker 组
sudo usermod -aG docker opc

# 启动并设置开机自启
sudo systemctl start docker
sudo systemctl enable docker
```

---

## Q3: 项目代码是否就位？

### 检查命令

```bash
ls -la /home/opc/stock-tracker/
cd /home/opc/stock-tracker && git status
git remote -v
git branch -v
```

### 排查结果

| 项目 | 结果 |
|------|------|
| 项目目录 | `/home/opc/stock-tracker/` 存在 ✅ |
| Git 状态 | `On branch main`, working tree clean ✅ |
| 远程仓库 | ✅ |
| 最新提交 | ✅ |
| 关键文件 | Dockerfile, docker-compose.yml, scripts/ 等均存在 ✅ |

### 结论

✅ **正常** — 代码已就位且为最新。

### 如果异常，修复方法

```bash
# 首次克隆
sudo mkdir -p /home/opc/stock-tracker
sudo chown opc:opc /home/opc/stock-tracker
git clone -b main https://github.com/<username>/stock-tracker.git /home/opc/stock-tracker

# 更新代码
cd /home/opc/stock-tracker
git pull origin main
```

---

## Q4: SELinux 是否正确配置？

### 检查命令

```bash
getenforce
getsebool container_connect_any
getsebool httpd_can_network_connect
```

### 排查结果

| 项目 | 结果 |
|------|------|
| SELinux 状态 | Enforcing ✅ |
| container_connect_any | on ✅ |
| httpd_can_network_connect | on ✅ |

### 结论

✅ **正常** — SELinux 策略已正确配置，允许容器连接网络和 Nginx 做反向代理。

### 如果异常，修复方法

```bash
# 允许 Docker 容器连接网络
sudo setsebool -P container_connect_any 1

# 允许 Nginx (httpd) 做反向代理连接
sudo setsebool -P httpd_can_network_connect 1
```

---

## Q5: Docker 容器是否正常运行？

### 检查命令

```bash
cd /home/opc/stock-tracker
sudo docker compose ps
sudo docker compose logs --tail=20
curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/
```

### 排查结果

| 项目 | 结果 |
|------|------|
| 容器名 | stock-tracker ✅ |
| 镜像 | stock-tracker-web ✅ |
| 状态 | Up (healthy) ✅ |
| 端口映射 | 0.0.0.0:8000→8000/tcp ✅ |
| 本地访问 | HTTP 200 OK ✅ |
| 日志 | 正常处理请求，无报错 ✅ |

### 结论

✅ **正常** — 容器运行健康，Web 服务响应正常。

### 如果异常，修复方法

```bash
cd /home/opc/stock-tracker

# 查看详细日志
sudo docker compose logs --tail=50

# 重新构建并启动
sudo docker compose down
sudo docker compose build --no-cache
sudo docker compose up -d

# 检查容器内部
sudo docker compose exec web bash
```

---

## Q6: Nginx 反向代理是否配置正确？

### 检查命令

```bash
# 安装状态
rpm -q nginx
nginx -v

# 服务状态
sudo systemctl is-active nginx
sudo systemctl is-enabled nginx

# 配置检查
sudo nginx -t
cat /etc/nginx/conf.d/stock-tracker.conf

# 端口监听
sudo ss -tlnp | grep -E ':80|:443'

# 本地代理测试
curl -s -o /dev/null -w '%{http_code}' -H 'Host: <配置的域名>' http://127.0.0.1:80/
```

### 排查结果

| 项目 | 结果 |
|------|------|
| Nginx 版本 | nginx/1.14.1 ✅ |
| 服务状态 | active (running), enabled ✅ |
| 配置语法 | syntax is ok, test is successful ✅ |
| 配置文件 | `/etc/nginx/conf.d/stock-tracker.conf` 存在 ✅ |
| server_name | <域名> ✅ |
| proxy_pass | http://127.0.0.1:8000 ✅ |
| 80 端口监听 | 是 ✅ |
| 通过代理访问 | HTTP 200 OK ✅ |

### 结论

✅ **正常** — Nginx 反向代理配置正确。

### 最终 Nginx 配置 (certbot 自动修改后)

```nginx
# /etc/nginx/conf.d/stock-tracker.conf

server {
    server_name <配置的域名>;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    listen 443 ssl; # managed by Certbot
    ssl_certificate /etc/letsencrypt/live/<配置的域名>/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/<配置的域名>/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;
}

server {
    if ($host = <配置的域名>) {
        return 301 https://$host$request_uri;
    }

    listen 80;
    server_name <配置的域名>;
    return 404;
}
```

### 如果异常，修复方法

```bash
# 安装 Nginx
sudo dnf install -y nginx

# 创建配置
sudo tee /etc/nginx/conf.d/stock-tracker.conf << 'EOF'
server {
    listen 80;
    server_name <配置的域名>;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF

# 允许 Nginx 做反向代理
sudo setsebool -P httpd_can_network_connect 1

# 测试并重启
sudo nginx -t && sudo systemctl restart nginx && sudo systemctl enable nginx
```

---

## Q7: 防火墙 (firewalld) 是否放行了必要端口？

### 检查命令

```bash
sudo systemctl is-active firewalld
sudo firewall-cmd --list-all
```

### 排查结果

**⚠️ 发现问题！**

| 项目 | 排查时状态 | 修复后状态 |
|------|-----------|-----------|
| firewalld | active ✅ | active ✅ |
| ssh 服务 | 已放行 ✅ | 已放行 ✅ |
| **http (80)** | **❌ 未放行** | **✅ 已放行** |
| **https (443)** | **❌ 未放行** | **✅ 已放行** |
| 17890/tcp | 已放行 | 已放行 |

### 问题原因

防火墙只放行了 `ssh` 和 `17890/tcp`，HTTP (80) 和 HTTPS (443) 端口被 firewalld 拦截，导致外部无法访问 Nginx。

### 修复命令

```bash
# 放行 HTTP 和 HTTPS
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-service=https

# 重载使规则生效
sudo firewall-cmd --reload

# 验证
sudo firewall-cmd --list-all
# 应看到 services: http https ssh
```

### 修复后验证

```bash
# 从外部测试 80 端口连通性 (Windows PowerShell)
Test-NetConnection -ComputerName <公网IP> -Port 80
# 结果: TcpTestSucceeded : True ✅

Test-NetConnection -ComputerName <公网IP> -Port 443
# 结果: TcpTestSucceeded : True ✅
```

### ⚠️ 别忘了 Oracle Cloud Security List

除了 OS 层面的 firewalld，还需要在 **Oracle Cloud 控制台** 的 Security List 中放行入站规则：

1. 登录 [Oracle Cloud Console](https://cloud.oracle.com/)
2. **Networking** → **Virtual Cloud Networks** → 你的 VCN
3. **Subnets** → 点击实例所在子网
4. **Security Lists** → 默认安全列表 → **Add Ingress Rules**

| Source CIDR | Protocol | Dest Port | Description |
|-------------|----------|-----------|-------------|
| `0.0.0.0/0` | TCP | 80 | HTTP |
| `0.0.0.0/0` | TCP | 443 | HTTPS |

---

## Q8: HTTPS 证书是否已配置？

### 检查命令

```bash
certbot --version
sudo ls /etc/letsencrypt/live/
sudo certbot certificates
```

### 排查结果

**⚠️ 发现问题！**

| 项目 | 排查时状态 | 修复后状态 |
|------|-----------|-----------|
| Certbot 安装 | 已安装 (1.22.0) ✅ | ✅ |
| python3-certbot-nginx | 已安装 ✅ | ✅ |
| **SSL 证书** | **❌ 未申请 (目录不存在)** | **✅ 已申请** |
| 证书路径 | — | `/etc/letsencrypt/live/<配置的域名>/` ✅ |
| 证书有效期 | — | 到 2026-07-14 ✅ |
| 自动续期 | — | 已配置 ✅ |
| HTTP→HTTPS 重定向 | 否 | 是 ✅ |

### 问题原因

Certbot 和 Nginx 插件已安装，但从未执行过证书申请命令。

### 修复命令

```bash
# 申请证书并自动配置 Nginx（含 HTTP→HTTPS 重定向）
sudo certbot --nginx \
    -d <配置的域名> \
    --non-interactive \
    --agree-tos \
    --register-unsafely-without-email \
    --redirect
```

### 输出确认

```
Successfully received certificate.
Certificate is saved at: /etc/letsencrypt/live/<配置的域名>/fullchain.pem
Key is saved at:         /etc/letsencrypt/live/<配置的域名>/privkey.pem
This certificate expires on 2026-07-14.
Successfully deployed certificate for <配置的域名> to /etc/nginx/conf.d/stock-tracker.conf
Congratulations! You have successfully enabled HTTPS on https://<配置的域名>
```

### 后续维护

```bash
# 查看证书状态
sudo certbot certificates

# 手动测试续期
sudo certbot renew --dry-run

# 手动续期
sudo certbot renew
```

---

## Q9: DNS 解析是否正确？

### 检查命令

```bash
dig +short <配置的域名>
nslookup <配置的域名>
```

### 排查结果

| 项目 | 结果 |
|------|------|
| 域名 | <配置的域名> ✅ |
| 解析 IP | <公网IP> ✅ |
| 与服务器 IP 一致 | 是 ✅ |

### 结论

✅ **正常** — DNS A 记录已正确指向服务器公网 IP。

---

## Q10: 最终的外部访问验证

### 验证命令

```powershell
# Windows PowerShell
Invoke-WebRequest -Uri 'https://<配置的域名>/' -TimeoutSec 10 -UseBasicParsing | Select-Object StatusCode, StatusDescription
```

### 结果

```
StatusCode StatusDescription
---------- -----------------
       200 OK
```

### HTTP 重定向验证

访问 `http://<配置的域名>` 会自动 301 重定向到 `https://<配置的域名>`。

### 结论

✅ **https://<配置的域名> 正常访问！**

---

## 排查结果总结

### 发现的问题及修复

| # | 问题 | 原因 | 修复方法 | 状态 |
|---|------|------|---------|------|
| 1 | 外部无法访问 80/443 端口 | firewalld 未放行 http/https 服务 | `sudo firewall-cmd --permanent --add-service={http,https} && sudo firewall-cmd --reload` | ✅ 已修复 |
| 2 | HTTPS 无法访问 | 未申请 Let's Encrypt SSL 证书 | `sudo certbot --nginx -d <配置的域名> --non-interactive --agree-tos --register-unsafely-without-email --redirect` | ✅ 已修复 |

### 修复后各组件状态

| 组件 | 状态 |
|------|------|
| 操作系统 | Oracle Linux 8.6 aarch64 ✅ |
| Docker 26.1.3 + Compose v2.27.0 | 运行中 ✅ |
| 容器 (stock-tracker) | Up, healthy ✅ |
| SELinux (Enforcing) | 策略已配置 ✅ |
| Nginx (反向代理) | 运行中, HTTPS + HTTP→HTTPS 重定向 ✅ |
| SSL 证书 | Let's Encrypt, 有效期至 2026-07-14, 自动续期 ✅ |
| 防火墙 (firewalld) | http, https, ssh 已放行 ✅ |
| DNS | <配置的域名> → <公网IP> ✅ |
| **最终访问** | **https://<配置的域名> → 200 OK** ✅ |

---

## 附录：完整排查流程图

```
SSH 连接服务器
    │
    ├─ 1. 系统环境 ──────────── ✅ OK
    │     (OS/架构/SELinux/磁盘/内存)
    │
    ├─ 2. Docker ─────────────── ✅ OK
    │     (版本/服务/用户组)
    │
    ├─ 3. 项目代码 ──────────── ✅ OK
    │     (目录/Git 状态/远程仓库)
    │
    ├─ 4. SELinux 策略 ────────── ✅ OK
    │     (container_connect_any/httpd_can_network_connect)
    │
    ├─ 5. Docker 容器 ─────────── ✅ OK
    │     (状态/健康检查/本地访问)
    │
    ├─ 6. Nginx ──────────────── ✅ OK
    │     (服务/配置/反向代理)
    │
    ├─ 7. 防火墙 ─────────────── ❌ → 修复 → ✅
    │     (firewalld 未放行 80/443)
    │
    ├─ 8. HTTPS 证书 ──────────── ❌ → 修复 → ✅
    │     (certbot 未申请证书)
    │
    ├─ 9. DNS 解析 ────────────── ✅ OK
    │
    └─ 10. 外部访问验证 ────────── ✅ 200 OK
```
