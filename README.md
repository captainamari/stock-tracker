# Stock Tracker

[English](README_EN.md) · [部署与升级](DEPLOY.md) · [UI 验收记录](docs/progress/COMPACT_STOCK_UI_RESULTS.md) · [收藏与通知历史验收](docs/progress/GUEST_WATCHLIST_RESULTS.md)

免登录的美股观察网站，保留 FastAPI、Jinja2、原生 JavaScript、Chart.js、SQLite WAL、yfinance 和 notification-hub。概览和“我的关注”由当前浏览器收藏驱动；“发现股票”提供完整公开目录。服务器采集池、浏览器收藏和所有者私人通知名单互不覆盖。

## 启动

Python 3.12，虚拟环境内安装 `requirements.txt`。先显式设置绝对 `STOCK_DB`，原生进程不会自动加载 `.env`。

```sh
export STOCK_DB=/absolute/path/stock_tracker.db
export PUBLIC_URL=http://127.0.0.1:8000
python -m lib.cli init
uvicorn web.app:app --host 127.0.0.1 --port 8000
# 另开两个终端，使用相同环境和数据库：
python -m lib.cli worker
python -m lib.cli scheduler
# 服务器维护命令：
python -m lib.cli assets
python -m lib.cli update
python -m lib.cli runs
```

Windows PowerShell 使用 `$env:STOCK_DB='C:\absolute\stock_tracker.db'`，其余 Python 命令相同。公开网站无登录、注册或管理员入口，也没有管理写入 API。维护方式见 `python -m lib.cli --help` 和部署文档。

## 收藏和页面

首次访问收藏 AAPL、MSFT、AMZN、GOOG、META、NVDA、TSLA、SPY、QQQ，唯一默认配置为 `config/browser-watchlist.json`。仅在未初始化时写默认值；主动清空后保持为空。支持排序、取消、明确确认恢复默认、JSON 导入导出、同源多标签同步。仅保存 `{version:1,symbols:[...]}`，上限100个代码，不保存行情或私人标签。

收藏保存在当前浏览器，清除网站数据后会丢失，不会自动跨设备同步。存储受限或写入失败会持续提示，当前标签页仍可使用；损坏或未知版本可通过导入/恢复默认修复。导入只接收明确格式并验证公开覆盖，未知/私人代码拒绝导入，不会添加服务器采集资产。

概览先展示日期状态与紧凑市场摘要，再显示关注表格；“我的关注”直接管理列表；“发现股票”搜索完整公开目录。三页共用语义化股票表格，桌面默认策略列，手机默认行情列，可切换“行情 / 策略”。表头可排序，策略评分排序必须先选具体策略；所有排序、筛选先处理完整集合，再分页。每页数量位于分页区。普通行约 50px，手机仅固定股票身份列，所有行共用表格横向滚动。

星标可直接收藏/取消。需要调整顺序时点击“编辑列表”；只有无搜索/策略/状态筛选、且按收藏顺序查看时可操作，移动对应完整收藏列表。“添加股票”进入发现页；“管理收藏”收纳导入、导出、恢复默认与清空。导入按钮打开文件选择器，覆盖操作均需确认，Escape 可关闭管理菜单。手机高级筛选默认折叠。

策略计数条可点击筛选候选，计数使用“我的关注”或“全部股票”的完整范围，不受搜索及其他筛选影响。同一股票可命中多种策略，数量不能相加当作股票数。确认变化单独呈现；前后有效交易日不齐时明确无法确认。固定市场广度及其有效/应统计/缺失分母不随收藏变化。SPY/QQQ 不适用的策略明确显示“不适用”。“历史数据可用”和“等待最新批次”分别表达。

详情保留历史导出、条件与指标，并提供 1M/3M/6M/1Y/全部图表区间；只筛选当前批次保存的日线，历史不足不补造数据。策略摘要先展示，完整条件与指标按需展开。返回链接保留来源页的筛选、排序、页码、列组合及页面/表格滚动位置（浏览器会话存储可用时）。

网页日报默认“按当前收藏查看该日行情”，可显式切换全部公开范围；表格复用同一列定义，保留冻结条件、前日比较及20交易日历史走势展开，历史市场背景折叠。价格、来源、图表与策略绑定原报告批次。旧纯文本报告只能显式展开完整公开快照。私人历史报告始终不可公开访问。后续加载保留已有结果并标记忙碌，失败可重试，旧响应不会覆盖新筛选。

`GET /api/assets?symbols=AAPL,SPY&batch=...` 按集合选择后筛选分页；空 `symbols=` 返回空集合，省略表示发现目录。支持 search、strategy、match、sort、page、size 和公开 report_id。每页20/50/100条，所有代码均由服务器验证当前和冻结时的公开权限，禁用缓存，私人条目仅返回无数据的“不可用”占位。GET 不调用 Yahoo、不刷新名单、不排队任务。首屏只服务端渲染市场背景，收藏数据与背景锁定同一批次。

## 采集与市场广度

采集保持 **标普500 ∪ 纳斯达克100 ∪ 启用的额外配置**，另保留 SPY、QQQ、IWM、VIX。Yahoo 别名去重，GOOG/GOOGL 不合并。退出指数不删除历史，主动停用和已有隐私设置不会被刷新覆盖。首次安装公开默认九只；升级保留私人冲突，`assets` 输出清单与逐个显式公开命令。

worker 每七天检查两份公开成分名单，失败保留上一份完整名单，至少24小时后重试。GET 不访问来源。新批次广度版本2使用该任务冻结的指数并集，不受个人额外股票、公开标记、收藏或通知名单影响，排除四个基准。保存总数、有效数、缺失数、覆盖率、逐指标有效分母和名单状态。缺失/停用成员仍计入总数；覆盖不完整时不生成完整市场状态；全缺失时百分比为空。旧报告仍标为历史公开观察池口径。

行情沿用 `auto_adjust=True` 的拆股/分红复权 OHLC 与原始成交量。首次获取800自然日，之后只请求最后保存交易日到最新已收盘交易日，并重叠校验末日。真实缺口、无效数据或复权变化才扩大回补，覆盖已存历史以保持复权一致；旧输入修订和冻结报告保留。历史不足252日的新股不会每天重抓。旧数据仍是 `legacy_unknown`。Yahoo 调用顺序执行、默认至少间隔5秒；限流停止整批并暂停6小时，保留上次发布。不能保证 IP 不被限流。

四个策略沿用原判定；收缩候选不等于确认突破，Checklist 分数不代表胜率，周线包含本周暂态。前一交易日无有效结果时不确认新增/退出。

## 独立私人通知

```sh
# 把示例复制到服务器私有位置，编辑名单；不要提交真实配置
cp config/daily-report.example.json /etc/stock-tracker/daily-report.json
python -m scripts.send_daily_report --config /etc/stock-tracker/daily-report.json --dry-run
# 下列命令会真实发送，仅由所有者在准备好后执行：
python -m scripts.send_daily_report --config /etc/stock-tracker/daily-report.json
```

脚本自行读取已发布数据、冻结配置/内容、调用现有 Hub 并退出，不要求另开通知 worker。默认目标是纽约交易日历最近已收盘交易日，支持 `--date YYYY-MM-DD`。名单必须已在采集范围内，空名单拒绝。Hub 地址/token 仍为 `NOTIFICATION_API_URL`/`NOTIFICATION_API_TOKEN`；JSON 只含渠道别名。

`profile + 目标交易日 + channel` 唯一约束防重复。未就绪发送并冻结延迟摘要，不自动补发；显式 `--manual-reissue --date ...` 才创建额外投递。重试复用冻结分段，成功部分不重复；超时/部分成功不自动重发。Hub 无远程幂等键，不保证网络级 exactly-once。`--dry-run` 不联网、不迁移、不写数据库。

独立 systemd 文件见 `deploy/stock-tracker-digest.service` / `.timer`，示例每天纽约06:00。原 scheduler 仅调度行情；旧 notify-worker 已移除。部署、退出码、人工核对和回滚见 [DEPLOY.md](DEPLOY.md)。本仓库变更不代表已部署或已真实通知。

## 验证

```sh
pip install -r requirements-dev.txt
python -m pytest -q
node --check web/static/js/main.js
node --check web/static/js/watchlist.js
node --check web/static/js/stock-table.js
node tests/frontend.test.cjs
python -m compileall -q lib web scripts
python -m playwright install chromium
python -m scripts.browser_acceptance --database /new/isolated-browser.db --artifacts /tmp/browser-evidence
```

浏览器验收只接受新库，生成两个已发布交易日的明确标记合成行情，并检查五类页面在 375、390、768、1024、1440、1920px 的布局及真实交互。输出 browser-results.json、compact-results.json 和代表性截图。保留增量采集、策略、统一批次、历史报告和 Hub 契约回归，不把合成数据当成真实市场数据。没有执行生产部署、真实发送或新的全市场性能实验。
