# 运行、迁移与恢复

本文件描述 S0–S4 可运行配置；不代表已执行生产部署。旧 `DEPLOY_QA.md` 中旧版流水线说明仅供历史参考，以本文件为准。

## 进程与配置

使用 Python 3.12。`web`、`worker`、`scheduler`、`notify-worker` 必须共享同一个本地 SQLite 文件/卷，不能放网络文件系统。SQLite WAL 允许网页读取与短写事务并行；网络下载和计算不持有写锁。worker 使用租约、心跳及写入 fencing，中断后新进程等待租约到期接管。最多一个活跃行情任务；多个进程不能绕过唯一约束。

原生启动见 README。环境变量集中于 `lib/settings.py`；管理页计划存于数据库。配置 `DISPLAY_TIMEZONE`、HTTPS 下 `COOKIE_SECURE=true`、正确 `PUBLIC_URL`。不要把 token 放 URL、前端或公开日志。原生启动不会自动读取 `.env`，需由服务管理器注入环境。

新安装 Docker Compose（以下命令仅供操作手册，本次未在 VPS 执行）：

```sh
cp .env.example .env
# 编辑 .env 的 URL / cookie / 可选 hub 连接；不要提交凭据
docker compose build
docker compose run --rm web python -m lib.cli init
docker compose run --rm -it web python -m lib.cli init-admin
docker compose up -d
```

仅绑定 `127.0.0.1:8000`；公开访问应经 HTTPS 反向代理。同一个数据卷保留原项目名，迁移时核实真实 volume 名称，不要误建空卷。初始化管理员交互输入密码，不能覆盖既有管理员。可选首次配置种子 `docker compose run --rm web python -m lib.cli seed-watchlist`（默认私人）。通过网页维护配置、执行更新。worker、scheduler、notify-worker 使用同一镜像且独立重启。

## 从旧版本切换前

1. 记录当前镜像/提交、真实数据库路径、volume 名称及 cron/systemd 定时项。停止旧写任务和旧直接 Telegram 计划；旧 `daily_pipeline.py`、`daily_update.sh`、采集和部署脚本在新代码中明确退出，不能继续安装旧 cron。
2. 停止写进程，使用下面的 SQLite backup API 备份到新路径，保留生产 DB、CSV、历史记录；恢复副本并检查完整性。
3. 在副本运行 `python -m lib.cli init`，检查 `schema_migrations` 和旧行数。迁移为增量事务，保留旧表，来源不明标记 `legacy_unknown`；仅新统一采集结果会成为已验证发布。
4. 验证副本登录、观察池隐私、完整范围导出、一次小池更新，再安排生产切换窗口。新启动只保留 Compose scheduler 或对应常驻服务，不能同时保留旧 cron。
5. 生产 DB 升级前做新备份。失败时停全部写进程，将备份恢复到另一新路径，先核实，再显式切换 `STOCK_DB`/卷挂载并使用对应旧版本。工具不会原地覆盖数据库。

## 一致性备份与恢复

```sh
# 原生：STOCK_DB 指向源，destination 必须不存在
python -m lib.cli backup /safe/new-backup.db
python -m lib.cli restore /safe/new-backup.db /isolated/new-restored.db
# Docker：备份写入持久化卷后由运维复制到外部备份位置
docker compose exec web python -m lib.cli backup /app/data/backup-NEW.db
```

使用 SQLite backup API，包含一致快照而非直接复制活跃 `.db`；恢复执行 `integrity_check` 且拒绝覆盖目标。恢复演练在隔离路径，不删除原库。CSV 导出来自发布批次的完整源修订，不充当数据库备份；旧 CSV 只能 `python scripts/migrate_prices.py --source PATH` 只读审计，不导入价格。

## 通知与实际契约

契约固定验证 `captainamari/notification-hub@7c6ef039047e9adae7c6ca14d4e32204f352957c`：Bearer `POST /api/v1/notify`，请求 `title/message/channel/level/source/metadata`，返回 `request_id/status/channel/delivered_to/skipped/failed`。hub 不提供幂等键或回执查询。

Stock Tracker 只保存 `trading` 等渠道引用，hub 保存 Telegram/SMTP 目标与凭据。设置 `NOTIFICATION_API_URL` / `NOTIFICATION_API_TOKEN`，管理页保存计划不发送，明确测试按钮才入队。默认禁用真实通知。06:00 目标为那一刻最近完成交易日，scheduler 停机后补检查仍使用计划时刻目标，避免把晚间新收盘误当早晨目标。每纽约交易日每种计划最多一次；缺报告发送缺失摘要，源修订不默认重发。

长报告冻结分段。成功分段不重复发送；连接未建立、429 可限次重试；读写超时、502、无效回执、部分成功一律保留 `unknown/partial`，管理员核对后可“确认处理，不重发”。不能证明 exactly-once。没有第二个直接 Telegram 后端同时运行。

```sh
git clone https://github.com/captainamari/notification-hub ../notification-hub
git -C ../notification-hub checkout 7c6ef039047e9adae7c6ca14d4e32204f352957c
pip install -r requirements-dev.txt
python -m scripts.verify_hub_contract --checkout ../notification-hub
```

该测试执行真实 hub 路由、鉴权、schema、路由/回执逻辑，仅替换 Apprise 网络边界。不会发送真实渠道消息，也不修改 hub。

## S5 生产验收（本次未执行）

- 核实 VPS 数据路径、磁盘容量、SQLite 本地盘和文件权限，备份保存与隔离恢复可用。
- 核对 TLS、Secure/SameSite/HttpOnly cookie、反向代理及管理员登录，访客写入/隐私隔离。
- 停旧 cron、旧 worker 和直连 Telegram；启动新四进程并验证重启、过期租约接管。
- 实地观察纽约 04:00 / 06:00、假日/DST 的计划记录、最新行情日期和缺失告警。
- 经用户另行授权，用真实 hub 凭据验证真实 Telegram/Email 收件与超时人工核对流程。
- 对照已验证备份执行回滚演练，记录实际版本、路径、监控及恢复耗时。


## Yahoo 请求控制与真实数据复用

默认每次 yfinance history 调用至少间隔 5 秒，顺序采集，已有历史仅检查 45 天重叠区间；缺失、复权变化才扩展为 800 天窗口。单次 history 可能发出多个 HTTP 请求，所以这不是 Yahoo 官方配额。遇到 YFRateLimitError / HTTP 429，立即停止整个任务，保留上次发布，数据库持久化暂停 6 小时；重启或重复点击不能绕过。暂停期间尝试任务会失败但不访问来源；到期后由下一次定时或手动更新再试，不自动循环重试。其他错误最多三次，退避 10/30 秒。管理页任务进度显示暂停截止时间。环境变量 YAHOO_MIN_INTERVAL_SECONDS / YAHOO_COOLDOWN_SECONDS 可调。无法保证 Yahoo 不限制 VPS IP；请先验收小观察池，观察日期、失败原因与请求频率。

5,004 个资产在默认间隔下仅请求启动间隔就需约 6 小时 57 分钟，另加下载和计算，无法用合成容量结果证明 04:00 开始会在 06:00 前完成。需按真实观察池大小调整计划并实测；通知到时缺报告仍使用明确缺失摘要。

git pull **只拉代码，不含数据库**。容量测试的 126 万行全部是隔离合成数据，不能部署为行情。真实验证库只有六个资产的 3,300 行，可通过 SQLite backup API 的一致副本单独传输，节省首次历史下载。

新安装可将经校验的真实备份上传到独立位置，然后恢复到不存在的目标（以下路径为示例；已有 VPS 必须保留原数据库并走上文迁移步骤）：

~~~sh
sha256sum /safe/real-market-bootstrap-2026-10-20.db
python -m lib.cli restore /safe/real-market-bootstrap-2026-10-20.db /new/stock-data/stock_tracker.db
export STOCK_DB=/new/stock-data/stock_tracker.db
python -m lib.cli init
python -m lib.cli init-admin
~~~

Docker 部署必须把恢复后的库放入实际 stock-data 挂载卷，单纯上传到仓库目录不会被容器读取。生产 PUBLIC_URL、TLS cookie 和 hub 配置单独设置，四进程指向同一库。交付的真实 bootstrap 已去除临时账号、会话、登录尝试、通知配置和投递记录，通知默认关闭；旧日报的冻结 localhost 链接保留来源，不伪改历史。恢复后先检查六资产行情、日期、详情和日报，再决定更新。不得用这个小样本库覆盖已有 VPS 配置或历史。以上仅为后续 S5 操作说明，本次没有连接或修改 VPS。
