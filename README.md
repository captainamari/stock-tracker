# Stock Tracker

[English](README_EN.md) · [启动与迁移](DEPLOY.md) · [本批验收证据](docs/progress/DAILY_USE_S1_S4_RESULTS.md)

每日美股观察：yfinance 已收盘日线 → SQLite → 策略与技术指标 → 原子发布看板和冻结日报 → notification-hub。保留 FastAPI、Jinja2、原生 JavaScript、Chart.js 和 SQLite WAL。

公开页面只读。单管理员可维护观察池、执行更新、查看持久化任务及配置通知。所有价格、指标、策略来自统一更新流程，没有人工数值录入或行情 CSV 上传。历史不足仍展示已有价格，缺失、过期、失败与不匹配分别标记。

## 本地启动

需要 Python 3.12。以下以 PowerShell 为例，先创建虚拟环境并安装依赖：

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:STOCK_DB = "$PWD/data/local.db"
$env:COOKIE_SECURE = 'false' # 仅限本机 HTTP；HTTPS 使用 true
$env:PUBLIC_URL = 'http://127.0.0.1:8000'
python -m lib.cli init
python -m lib.cli init-admin
uvicorn web.app:app --host 127.0.0.1 --port 8000
```

另开终端，激活相同环境并设置同一个绝对 `STOCK_DB`，分别运行：

```text
python -m lib.cli worker
python -m lib.cli scheduler
python -m lib.cli notify-worker
```

访问 `/admin` 登录，在“观察池与数据”新增 AAPL/MSFT（默认私人，勾选公开才对访客可见），点击“更新数据”。关闭页面不会取消任务。可选 `python -m lib.cli seed-watchlist` 仅为空观察池导入 `config/tickers.json`，定时任务不重导 JSON；向非空库导入配置必须显式 `--explicit`，不导入价格。

## 日期、策略与日报

- 市场日历 XNYS，纽约时间交易日 04:00 更新最近已收盘交易日，06:00 独立通知；管理员修改后由 scheduler 自动读取，免改 cron。默认关闭通知。
- 行情为 yfinance `auto_adjust=True` 的拆股/分红复权 OHLC、原始成交量。回看重采缺口、修订及公司行动，不换口径、不填补缺失。旧数据保留为 `legacy_unknown`，不冒充已验证行情。
- Stage2 为完整 8 项必要条件；收缩候选保留原 VCP 规则（不宣称确认突破）；逆势观察独立分区；Checklist 分数不是胜率，周线含本周暂态。
- 每批保存规则版本、输入修订和完整结果，页面、API、CSV、日报按同一发布批次读取。失败不伪造退出；零候选不回填旧信号；持续活跃保留进入日期。
- hub 默认地址为 `https://notify.watchpoint.space`，可用 `NOTIFICATION_API_URL` 覆盖；`NOTIFICATION_API_TOKEN` 必须通过服务器私有环境注入。管理页渠道引用默认 `trading`（Telegram），已有保存的渠道不会被覆盖。Telegram/SMTP 凭据只归 hub。保存设置不发送；测试发送需明确按钮操作。配置步骤见 [DEPLOY.md](DEPLOY.md#公网通知服务配置)。
- hub 当前没有远程幂等键或回执查询。超时/部分投递标记待核对，不自动重发；可确认处理而不重发。安全连接失败分段最多尝试三次。长日报按固定快照分段，成功分段不重复发。缺目标日报发送缺失摘要，不自动补发。

## 验证

```text
pip install -r requirements-dev.txt
python -m pytest -q
node --check web/static/js/main.js
python -m compileall -q lib web scripts
python -m scripts.capacity_check --database /new/path/synthetic.db --output /new/path/capacity.json
```

容量工具只接受新数据库，使用明确标记的合成 5,000 股 × 252 日线，执行真实采集规范化、计算、存储、发布和并发网页读取；不是全市场真实采集证明。hub 契约测试见 [DEPLOY.md](DEPLOY.md)。旧独立采集、策略 CLI、直接 Telegram 调度及自动部署脚本已停用，避免重复写入/推送；算法函数保留供统一计算调用。

S5 的生产 VPS 切换、真实渠道投递、线上备份恢复演练尚未执行。详细限制与逐项 A01–A19 证据见验收记录。

Yahoo 请求默认顺序执行、每次 history 调用间隔至少 5 秒；限流时整个任务停止，持久化暂停 6 小时并保留上次发布。无法保证 VPS IP 不受 Yahoo 限制。环境变量见 .env.example。git pull 不包含 SQLite 数据；126 万容量测试行是合成数据，只有单独的 3,300 行真实行情可通过备份供新安装复用，不能覆盖已有 VPS 库，步骤见 DEPLOY.md。

## 默认采集范围

默认采集 **标普 500 ∪ 纳斯达克 100 ∪ 已启用的个人观察股票**，另保留 SPY、QQQ、IWM、VIX 四个基准。2026-10-22 获取的初始名单为 503 + 101 个证券代码，其中重叠 86 个，去重后 **518 只指数成分股**。不同股份类别仍分别保留；BRK.B/BRK-B 等同一 Yahoo 代码的别名只采集一次。

空库先保留 config/tickers.json 原有的 44 个个人条目，再加入指数股票，当前默认配置合计 **540 个采集资产**。已有库的观察池视为个人条目，保留名称、Yahoo 映射、停用选择和隐私设置，不被名单覆盖；新增纯指数条目默认公开。通过现有“添加股票”表单保存指数股票，可将其同时保留为个人观察条目。

worker 在完整名单满七天后的下一次更新开始前检查两份公开成分股表。获取或校验失败保留上次完整名单，至少 24 小时后重试；页面和 GET API 不访问名单或行情源。每个任务在采集前固定名单，进程重启继续使用同一范围。退出指数且非个人保留的股票停止采集，历史行情和日报不删除；主动停用的股票不会被刷新重新启用。

观察池与管理页显示名单数量、获取时间及刷新异常，管理页区分个人与指数维护条目。INDEX_UNIVERSE_ENABLED=false 可仅采集个人观察池和四个基准，不删除历史。本次配置完成后新增股票仍为“待更新”，并不表示已下载 518 只股票的真实行情。
## 个人标签、分页与日报

观察池与管理页默认每页 20 条，可切换 50 / 100 条。搜索、关注/持有范围及策略筛选作用于完整结果后再分页；链接保留筛选和行情批次。概览每个策略最多展示五项，点击“查看全部”进入筛选后的观察池。更新记录、单次任务进度及通知记录也支持分页。

登录后可独立设置“关注”和“持有”，也可选择本页股票批量修改。标记只向管理员显示，与公开/私人可见性独立。取消标记不会停用采集；标记一个指数成分股会将其保留为个人条目，退出指数后仍可采集。首次升级将已有个人条目设为关注，持有默认留空；以后启动不会重置个人选择。新安装的配置条目和手动添加的股票默认关注。

每次成功更新同时冻结公开、关注、持有、关注或持有四份日报。网页先展示市场背景、确认变化和数据异常，再展示可筛选分页的个股行情/四策略矩阵、20个交易日收盘价小图（缺失日留空）及可展开的条件解释。日报保存生成时的名单和标记，历史不会随当前名单编辑而改变；私人日报需要管理员登录。旧版报告仍按原文本读取，升级后第一次更新才生成新的个人日报，不根据今天的持仓追补旧名单。

管理员“通知计划”可选择关注、持有或二者并集，默认并集；标准版包含全部行情及匹配/接近策略详情，精简版每个策略最多五项，持有优先。通知参考 v1 的分组、条件进度条、评分、均线及未满足条件说明，通过现有 Hub 发送纯文本。页面中的“预览，不发送”只读取目标交易日已保存快照，不下载行情、不计算策略、不创建投递。保存通知设置也不会立即发送。

前一交易日缺失或评估失败时，日报不会确认新增/退出或展示虚假的前后分数差异；行情异常和策略输入不足分别标记。分数不是胜率；收缩不代表已突破；Checklist 周线包含本周暂态。目标日没有所选范围日报时发送缺失摘要，不替换为公开池或旧日报。既有队列的内容保持冻结，通知的去重与不确定投递处理规则不变。

English: lists paginate after filtering the full visible collection (20/50/100). Private Following/Held labels are independent of public visibility and collection enablement. Successful publications freeze public and three personal report scopes; personal reports require sign-in. Existing personal rows migrate to Following once, never inferred Held. Notification preferences select scope and standard/compact detail. Preview is read-only and never queues delivery. v1-inspired plain text works with the existing notification-hub contract; no hub upgrade is required. Historical legacy reports remain text, with personal snapshots starting on the next update. No deployment is performed by this change.
