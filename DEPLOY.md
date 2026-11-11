# 部署、升级与回滚

本说明对应免登录网站与独立日报版本。部署与真实通知须由所有者另行执行；本次代码改造不操作 VPS。英文用户可参考 README_EN 与下面的命令、退出码和路径。

## 进程与权限

Python 3.12；`web`、行情 `worker`、行情 `scheduler` 与独立日报脚本共享**同一个本地盘 SQLite WAL**，使用相同账号或兼容权限。不要使用网络文件系统。保留现有数据库绝对路径、卷名称、Yahoo 限流配置及实际更新时间，不新建空库替换旧库。

原生部署推荐目录：代码 `/opt/stock-tracker`，虚拟环境 `/opt/stock-tracker/.venv`，数据库 `/var/lib/stock-tracker/stock_tracker.db`，私有环境 `/etc/stock-tracker/runtime.env`，私有日报配置 `/etc/stock-tracker/daily-report.json`，账号/组 `stock-tracker`。数据库目录必须可写以创建 WAL/SHM；私有配置建议0640，仅服务账号可读。仓库示例不包含凭据。

原生进程不自动加载 `.env`；由 systemd `EnvironmentFile` 注入。示例环境：

```ini
STOCK_DB=/var/lib/stock-tracker/stock_tracker.db
PUBLIC_URL=https://stocks.example.com
DISPLAY_TIMEZONE=Asia/Shanghai
INDEX_UNIVERSE_ENABLED=true
NOTIFICATION_API_URL=https://notify.watchpoint.space
NOTIFICATION_API_TOKEN=<服务器私有凭据>
YAHOO_MIN_INTERVAL_SECONDS=5
YAHOO_COOLDOWN_SECONDS=21600
```

公开 HTTP 没有登录/退出/管理员导航，原认证、采集增删、标签/可见性修改、手动更新、通知设置、预览、测试发送、重试/确认接口均不再挂载，旧 cookie 也不能访问。不存在公网管理 token 或隐藏管理 URL。语言 cookie 可保留。数据库认证表保留用于备份和回滚，不清除原账号数据。

Docker Compose 仅启动 web、worker、scheduler 三个服务。沿用真实卷名，不要变更 Compose project 导致误挂空卷。必须先 `docker compose run --rm web python -m lib.cli init`，然后启动三进程。旧 `notify-worker` 必须显式停止并删除旧容器，不能因服务从 Compose 文件消失就假定它已停止。若采用下面原生 systemd 日报，请将 `STOCK_DB` 映射到**相同实际本地数据目录**，核对 uid/gid；不要把容器内 `/app/data/...` 直接当宿主机路径。无需引入第四个常驻通知容器。

## 升级步骤

1. 记录当前提交/镜像、真实 STOCK_DB、卷名、环境文件、采集时间、旧 cron/systemd/Compose 服务。保留配置备份。停止旧通知 scheduler/worker 后核对未完成投递，避免切换期间发送。安排短暂停止行情写入，以便升级与回滚检查。
2. 使用 SQLite backup API 创建一致性备份，不能只复制活跃 `.db`。恢复到新隔离路径并检查：

   ```sh
   export STOCK_DB=/actual/existing/stock_tracker.db
   python -m lib.cli backup /safe/stock-before-guest.db
   python -m lib.cli restore /safe/stock-before-guest.db /isolated/upgrade-check.db
   export STOCK_DB=/isolated/upgrade-check.db
   python -m lib.cli init
   python -m lib.cli assets
   python -m lib.cli deliveries
   ```

   `backup` 和 `restore` 拒绝覆盖目标；restore 执行 integrity_check。历史行情、输入修订、公开/私人边界、报告和投递均保留。008 为加法迁移：`digest_runs` 防重表与任务 `universe_status` 字段；重复执行跳过已应用版本，不改写旧快照或旧广度标签。
3. 对隔离副本检查后，才在维护窗口对真实 STOCK_DB 执行相同 `init`。新安装公开默认九只；已有私人/停用配置保持原样。`assets` 输出默认冲突清单，审核后仅显式调整需要的标的，例如 `python -m lib.cli asset-public AAPL`；若原本停用，是否 `asset-enable AAPL` 也由所有者决定。不得批量公开历史私人标的。
4. 导出旧关注/持有配置，不启动发送：

   ```sh
   python -m lib.cli export-digest --scope personal --output /etc/stock-tracker/daily-report.json
   # --scope 可为 following / held / personal；personal 是二者并集
   ```

   输出目标必须不存在。检查名单、顺序、profile、渠道和 mode；可改用 `config/daily-report.example.json` 自定义。空名单必须人工填写。配置仅允许 version/profile/symbols/channel/mode，version=1，最多100个代码，去重保序；mode 为 standard/compact。未覆盖的代码明确报错，单独用 `asset-add` 加入后再安排行情更新。配置导出不会改变每个访客的收藏，不启用定时任务。
5. 在真实发送前预览（只读，无 Hub/队列/报告/行情/调度写入）：

   ```sh
   python -m scripts.send_daily_report --config /etc/stock-tracker/daily-report.json --dry-run
   python -m scripts.send_daily_report --config /etc/stock-tracker/daily-report.json --date 2026-10-20 --dry-run
   ```

6. 确认旧应用通知入口已关闭：本版本 `scheduler` 只调度行情，即使旧数据库 `enabled=true` 也不会排队通知。停用旧 `notify-worker`、通知 cron/旧 systemd；不要删除 `deliveries`/`delivery_parts`。用 `deliveries` 核查遗留 queued、retryable、sending、unknown、partial：新脚本不会顺手消费这些任务。核对后显式 retry 或 confirm，保留记录。重启新版 web/worker/scheduler，保留行情调度。
7. 所有者按下一节安装新 timer，检查状态与日志。不要同时安装 cron；本交付只提供 systemd 调度一种方案。没有 `update && send`，也没有更新成功回调。

## 独立 systemd 日报

文件：`deploy/stock-tracker-digest.service` 与 `deploy/stock-tracker-digest.timer`。检查实际 WorkingDirectory、Python 路径、User/Group、EnvironmentFile、STOCK_DB、ReadWritePaths 和 JSON 路径后再安装。服务中显式 STOCK_DB 与现有行情进程必须一致；私有环境文件也应填同一值。

```sh
# 先校验；缺少本机路径/账号时按实际部署修正
systemd-analyze verify deploy/stock-tracker-digest.service deploy/stock-tracker-digest.timer
systemd-analyze calendar --iterations=5 '*-*-* 06:00:00 America/New_York'
sudo install -m 0644 deploy/stock-tracker-digest.service /etc/systemd/system/
sudo install -m 0644 deploy/stock-tracker-digest.timer /etc/systemd/system/
sudo systemctl daemon-reload
# 只有完成配置、dry-run和旧任务核对后，由所有者启用：
sudo systemctl enable --now stock-tracker-digest.timer
systemctl list-timers stock-tracker-digest.timer
systemctl status stock-tracker-digest.service stock-tracker-digest.timer
journalctl -u stock-tracker-digest.service -n 100 --no-pager
# 停用：
sudo systemctl disable --now stock-tracker-digest.timer
```

示例每天纽约06:00触发，明确使用 `America/New_York`，不写固定 UTC 偏移。更改时间可编辑 timer/drop-in，并 daemon-reload/restart timer。`Persistent=true` 会在停机后触发一次，目标按**实际执行时刻最近已收盘交易日**选择，不追补停机期间每一天。周末、节假日、周一早晨可能指向同一最近交易日，由持久化唯一键防重。早收盘使用 XNYS 日历。

默认行情 scheduler 在纽约交易日04:00排队，06:00通知不保证行情已完成。周五收盘后到周一早晨可能还没有周五批次，独立日报会明确报告延迟并冻结该结果。保留用户实际更新时间，结合真实采集池耗时调整；可用 `update-schedule --time HH:MM` 设置每天交易日排队时间。540资产仅5秒调用间隔就约45分钟，重试/历史回补/限流会更久。不要用加速并发 Yahoo 请求赶通知。先观察真实 `runs`，按需由所有者选择合适的行情运行安排；缺数据时不换成旧日报。

服务只调用通知脚本，既不 Requires/After 行情服务，也不依赖其成功事件。20分钟超时可能留下不确定投递，不能以重启服务自动盲目补发。没有自动 Restart；状态和日志供人工处理。

## 通知入口、退出码和人工处理

```sh
# 默认最近已收盘交易日；此命令会发送
python -m scripts.send_daily_report --config /etc/stock-tracker/daily-report.json
# DAILY_REPORT_CONFIG 可代替 --config
python -m lib.cli deliveries
python -m lib.cli deliveries --id DELIVERY_ID     # 分段状态、尝试数、安全错误代码与回执 ID
python -m lib.cli delivery-confirm DELIVERY_ID     # 仅确认，不重发
python -m lib.cli delivery-retry DELIVERY_ID       # 明确重试，直接发送该任务的未成功部分
# 延迟摘要之后需要正式报告，或核对后明确需要另一份报告：
python -m scripts.send_daily_report --config /etc/stock-tracker/daily-report.json --date YYYY-MM-DD --manual-reissue
```

自动日报唯一键为稳定 profile + 目标交易日 + channel。同日更新批次、配置内容/顺序变化、跨自然日重跑均不会重发。首次正式操作冻结名单、配置摘要、内容和 batch；重试沿用这些分段。`--manual-reissue` 是额外投递，必须指定交易日，可能产生重复消息；原冻结记录不改写。换 profile 或渠道是新的逻辑投递身份，不能随意随机生成 profile。

明确未建立连接、429 是可重试；脚本尝试自己的任务后退出，后续再次运行或 `delivery-retry` 可继续，最多三次自动安全尝试。成功分段不会重发。超时、无效回执、部分投递、进程在发送中中断一律 unknown/partial，不能自动重试；先到真实渠道核对，再 confirm 或显式 manual-reissue。Hub 不提供远程幂等/回执查询，不能保证网络级 exactly-once。

| Exit | Meaning |
|---|---|
| 0 | 已发送/已确认，或 ready 的 dry-run |
| 2 | 配置、路径/权限或日期错误 |
| 3 | 目标批次缺失；正式运行已发送/冻结延迟摘要，dry-run 仅打印。systemd 视为可理解的完成状态 |
| 4 | 结果不确定、部分成功或另一进程发送中，人工核对 |
| 5 | Hub 未配置/拒绝/安全可重试，查看持久化状态 |
| 6 | 数据库不可读或未迁移 |

私人日报不挂在免登录网站，正文只链接公开概览。非指数个人股票可进入通知，但不改变市场广度。日志不输出 token、通知目标或原始网络异常。

## 服务器维护命令

```sh
python -m lib.cli assets
python -m lib.cli seed-watchlist --file /private/tickers.json --explicit
python -m lib.cli asset-add INTC --name Intel --public
python -m lib.cli asset-add MYPRIVATE --yahoo MYPRIVATE
python -m lib.cli asset-public INTC
python -m lib.cli asset-private INTC
python -m lib.cli asset-disable INTC
python -m lib.cli asset-enable INTC
python -m lib.cli update
python -m lib.cli runs --id RUN_ID
python -m lib.cli update-schedule
python -m lib.cli update-schedule --time 04:00
```

新增配置仅写入待更新资产，不下载行情。已有条目的隐私和 Yahoo 映射不会被 asset-add 覆盖，修改公开状态需专门命令。别名解析复用采集映射。保留 index stock 为额外配置后，即使退出指数仍采集。禁止通过 HTTP/CSV 手工写价格。原关注/持有数据只用于历史与私人配置导出，不注入访客收藏。

## 回滚

先停新 timer 和所有写进程，保存故障版本数据库及配置作为审计副本。恢复旧提交/镜像、旧服务文件和升级前环境配置；用 `restore` 将升级前备份恢复到**另一个新路径**，核对 integrity_check、行情/报告/投递与隐私后显式切换 STOCK_DB/卷。不得原地覆盖生产库。008 是增量迁移，但不宣称旧代码自动兼容所有新增报告；推荐代码和匹配备份成对回滚。恢复旧通知调度前先检查真实收件与已完成投递，避免旧调度再次发送。不要同时运行旧通知 worker 和新 timer。浏览器收藏仅在本机，回滚服务器不会同步或清除它。

## 验证与限制

```sh
pip install -r requirements-dev.txt
python -m pytest -q
node --check web/static/js/main.js
node --check web/static/js/watchlist.js
python -m compileall -q lib web scripts
python -m playwright install chromium
python -m scripts.browser_acceptance --database /new/synthetic-browser.db --artifacts /tmp/browser-evidence
# 真实 Hub 路由/schema，替换 Apprise 网络边界，不发送真实消息：
git clone https://github.com/captainamari/notification-hub ../notification-hub
git -C ../notification-hub checkout 7c6ef039047e9adae7c6ca14d4e32204f352957c
python -m scripts.verify_hub_contract --checkout ../notification-hub
```

本机为 Windows，没有 systemd/WSL，不能在本机声称 unit 原生执行通过。CI 增加 Linux systemd-analyze 校验与真实 Chromium 场景；实际运行结果见验收记录。未执行 VPS 部署、生产数据库迁移、真实通知或用户验收。旧 docs/progress 与 DEPLOY_QA 是历史证据，不作为本版本启动指南。
