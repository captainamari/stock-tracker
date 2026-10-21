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
- hub URL/token 通过环境注入，渠道引用在管理页设置。渠道与 Telegram/SMTP 凭据只归 hub。保存设置不发送；测试发送需明确按钮操作。
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
