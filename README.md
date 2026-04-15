# 📊 Stock Tracker — 美股技术分析与信号监控系统

基于 Stan Weinstein 阶段分析、Mark Minervini 趋势模板/VCP 理论、以及多维度量化抄底模型，构建的自动化美股分析管线。

## 总览

```
save_prices.py            → 数据采集层 ⚠️ 已弃用（Stooq 数据源不可用）
save_prices_yfinance.py   → 数据采集层 yfinance
        ↓
    SQLite DB (stock_tracker.db)
        ↓
market_pulse.py           → 策略0: 市场温度计（宏观全局视角，最先推送）
        ↓
stage2_monitor.py         → 策略1: Stage 2 趋势确认（基础层）
        ↓
vcp_scanner.py            → 策略2: VCP 右侧追涨（依赖 Stage 2）
bottom_fisher.py          → 策略3: 抄底左侧信号（独立运行）
        ↓
    Jinja2 模板 → reports/daily/ (MD + Telegram HTML)
        ↓
    web/app.py               → Phase 4: Web Dashboard (FastAPI + Chart.js)
        ↓
    lib/pipeline.py           → Phase 5: Web Ticker 管理（验证 + 拉取 + 策略管道）
```

### 策略定位对比

| 维度 | Market Pulse | Stage 2 Monitor | VCP Scanner | Bottom Fisher |
|------|-------------|----------------|-------------|---------------|
| **理论基础** | 多维市场温度计 | Stan Weinstein 四阶段 | Mark Minervini VCP | 技术抄底（均值回归） |
| **交易方向** | 宏观判定 | 趋势确认 | 右侧追涨 | 左侧抄底 |
| **扫描范围** | SPY/QQQ/IWM/VIX + 全池 | 全部监控股票 | 仅 Stage 2 股票 | 全部监控股票 |
| **核心问题** | "现在是进攻还是防御？" | "这只股票在上升趋势中吗？" | "Stage 2 中的哪只即将突破？" | "哪只好股票跌到底了？" |
| **信号含义** | 🟢进攻/🟡谨慎/🟠防御/🔴空仓 | 趋势健康 → 可持有 | 波动收缩 → 即将突破 | 超跌到位 → 买入窗口 |

---

## 项目演进路线

| Phase | 内容 | 状态 |
|-------|------|------|
| Phase 1 | 创建独立项目 + 数据库 Schema + `lib/db.py` + 数据迁移脚本（CSV→DB） | ✅ 已完成 |
| Phase 2 | 改造各策略脚本，计算结果存入 DB + 保留现有文件输出（双写过渡） | ✅ 已完成 |
| Phase 3 | 抽取 Jinja2 报告模板，报告从 DB 数据渲染 | ✅ 已完成 |
| Phase 4 | 开发 Web 应用（Dashboard + Watchlist + Ticker Detail） | ✅ 已完成 |
| Phase 5 | Web Ticker 管理（验证 + 新增 + 删除 + 单 Ticker Pipeline） | ✅ 已完成 |

---

## 架构设计

### 系统架构

```
┌──────────────────────────────────────────────────────────────┐
│                     config/tickers.json                       │
│                  个股 + 指数/ETF + SPY 基准                   │
└───────────────────────────┬──────────────────────────────────┘
                            │
         ┌──────────────────┼──────────────────┐
         ▼                  ▼                  ▼
  save_prices.py     save_prices_yfinance.py   lib/config.py
  (Stooq → 个股)     (yfinance → VIX/QQQ/IWM)  (sync_watchlist)
         │                  │                  │
         └────────┬─────────┘                  │
                  ▼                            ▼
         ┌────────────────────────────────────────┐
         │         SQLite: stock_tracker.db        │
         │  ┌───────────┐  ┌────────────────────┐ │
         │  │ watchlist  │  │   stock_prices     │ │
         │  └───────────┘  └────────────────────┘ │
         │  ┌───────────────────┐ ┌────────────┐  │
         │  │ strategy_results  │ │ market_pulse│  │
         │  └───────────────────┘ └────────────┘  │
         │  ┌───────────────────┐ ┌────────────┐  │
         │  │ strategy_states   │ │ db_meta     │  │
         │  └───────────────────┘ └────────────┘  │
         │  ┌───────────────────┐                  │
         │  │ signal_changes    │                  │
         │  └───────────────────┘                  │
         └──────────────────┬─────────────────────┘
                            │ lib/db.py (DAL)
           ┌────────────────┼────────────────────┐
           ▼                ▼                    ▼
     策略分析脚本      lib/indicators.py     lib/models.py
     (scripts/*.py)    (共享技术指标)        (数据模型)
           │                                      │
           ▼                                      ▼
     lib/report.py + templates/*.j2         lib/pipeline.py
           │                               (Web 单 Ticker 管道)
           ▼
     reports/daily/ (MD + Telegram HTML + manifest)
```

### 数据库 Schema (7 张表)

| 表名 | 用途 | 主键 |
|------|------|------|
| `watchlist` | 观察列表（同步自 tickers.json） | symbol |
| `stock_prices` | 日线 OHLCV 价格数据 | (symbol, date) |
| `strategy_results` | 策略每日计算结果（所有策略共享） | (symbol, date, strategy) |
| `strategy_states` | 策略当前状态跟踪（替代 state/*.json） | (symbol, strategy) |
| `signal_changes` | 信号进出历史记录 | id (自增) |
| `market_pulse` | 市场宏观状态 | date |
| `db_meta` | 数据库版本元数据 | key |

**设计要点**：
- `strategy_results` 使用 JSON 列（`conditions`, `condition_details`, `metrics`）存储策略特定数据，灵活扩展
- SQLite WAL 模式，提升并发读性能
- `_NumpyEncoder` 自动处理 numpy 类型的 JSON 序列化

### 数据流

```
tickers.json
     │
     ├── monitored[] + benchmark ──→ save_prices.py (Stooq)
     │                                     │
     ├── yfinance_only[] ────────→ save_prices_yfinance.py (yfinance)
     │                                     │
     │    ┌────────────────────────────────┘
     │    │              写入 stock_prices 表
     │    │              (365天 OHLCV)
     │    │
     ▼    ▼
market_pulse.py  ──→  market_pulse 表     (SPY+QQQ+IWM+VIX+宽度)
     │
stage2_monitor.py  ──→  strategy_results/states
     │                        │
     │                        ▼
     │                  vcp_scanner.py  ──→  strategy_results/states
     │
     ├──────────────→  bottom_fisher.py  ──→  strategy_results/states
     │
     └──────────────→  [Phase 4] Web Dashboard
```

---

## 数据采集层

### `save_prices.py` — Stooq 数据源

主力数据采集脚本，从 stooq.com 拉取 OHLCV 日线数据，覆盖 `tickers.json` 中的 个股 + SPY 基准。

### `save_prices_yfinance.py` — yfinance 数据源

补充数据采集脚本，从 Yahoo Finance 拉取 Stooq 不覆盖的 ticker，读取 `tickers.json` 的 `yfinance_only` 配置区。

| 对比项 | Stooq 版 | yfinance 版 |
|--------|---------|-------------|
| **覆盖** | 个股 + SPY | VIX / SPY / QQQ / IWM |
| **配置区** | `monitored[]` + `benchmark` | `yfinance_only[]` |
| **请求间隔** | 1 秒 | 2~3.5 秒（更保守） |
| **风险** | 无限流问题 | 有限流风险 |
| **存储** | SQLite DB + CSV 备份 | SQLite DB + CSV 备份 |

> ⚠️ 从 yfinance 切换到 Stooq 的原因：yfinance 限流严重，有被封 IP 的风险。Stooq 作为主力源，yfinance 仅用于拉取少量补充 ticker。

---

## 策略0: Market Pulse (`market_pulse.py` v3.0)

### 概述
市场宏观温度计。综合 SPY/QQQ/IWM 趋势 + VIX 恐慌指数 + 内部市场宽度 + 板块热度，输出市场整体状态判定。**在所有个股策略之前推送**，先看市场全貌再看个股信号。

### 设计原则
- 纯读 DB 数据，零网络请求
- 数据不可用时优雅降级（如缺少 VIX 数据，权重自动重分配）

### 5 大分析模块

#### ① SPY 趋势分析 (权重 30%)

| 指标 | 分值 | 说明 |
|------|------|------|
| 价格 > SMA50 | +10 | 短期趋势向上 |
| 价格 > SMA200 | +10 | 长期趋势向上 |
| SMA50 > SMA200 (金叉) | +10 | 均线排列健康 |
| SMA200 上升 | +5 | 长期趋势加速 |
| 价格 > EMA65 | +5 | 模拟周线趋势 |
| 周线排列 (EMA65 > EMA170) | +5 | 周线级别健康 |
| MACD > 0 | +8 | 动量正面 |
| MACD柱状图上升 | +7 | 动量加速 |
| 短期排列 (EMA8 > EMA21) | +5 | 短期走势正面 |
| 5日动量 > 0 | +3~10 | 近期走势正面 |
| RSI 健康区 (40-70) | +10 | 不超买不超卖 |
| 距52周高点 < 5% | +10 | 靠近新高 |
| EMA170 上升 | +5 | 长期趋势确认 |

#### ② QQQ 趋势分析 (权重 15%)
与 SPY 评分逻辑完全一致。代表纳斯达克科技股方向。

#### ③ IWM 趋势分析 (权重 10%)
与 SPY 评分逻辑完全一致。代表小盘股情绪（风险偏好指标）。

#### ④ VIX 恐慌分析 (权重 25%)

| VIX 区间 | 状态 | 评分 |
|----------|------|------|
| < 12 | 极度乐观 😎 | 100 |
| 12-15 | 乐观 | 85 |
| 15-18 | 正常 | 70 |
| 18-22 | 偏高 😟 | 55 |
| 22-25 | 恐慌 😨 | 40 |
| 25-30 | 高度恐慌 | 25 |
| 30-35 | 极度恐慌 🤯 | 10 |
| ≥ 35 | 崩溃 | 0 |

#### ⑤ 内部宽度分析 (权重 20%)

基于监控股票池计算内部市场宽度（非全市场）：

| 指标 | 最大分值 | 说明 |
|------|---------|------|
| 价格 > MA50 占比 | 35 | 短期参与度 |
| 价格 > MA200 占比 | 25 | 长期健康度 |
| Stage 2 占比 | 25 | 趋势确认浓度 |
| 5日上涨占比 | 15 | 即时动能 |

附加信息：板块热度排名（按 Stage 2 占比排序）。

### 综合评分与市场状态

| 评分区间 | 状态 | Emoji | 操作建议 |
|----------|------|-------|---------|
| ≥ 70 | BULLISH — 进攻 | 🟢 | 积极寻找 Stage 2 + VCP 入场机会 |
| 50-69 | NEUTRAL — 谨慎 | 🟡 | 方向不明，控制仓位，等待信号明确 |
| 35-49 | CAUTIOUS — 防御 | 🟠 | 弱势市场，减少新仓，保护利润 |
| < 35 | BEARISH — 空仓 | 🔴 | 下行趋势，现金为王，等待底部信号 |

**特殊修正规则**：
- VIX ≥ 30 → 强制降级为 🔴 BEARISH（恐慌飙升时暂停所有买入）
- SPY 跌破 SMA200 超过 3% → 最多降级为 🟠 CAUTIOUS（市场结构转弱）
- VIX < 13 且 BULLISH → 附加⚠️过度自满警告

### Regime Change 检测
自动检测市场状态变化。当 regime 发生切换（如 🟢→🟡），Telegram 推送会在头部高亮显示变化信息。

---

## 策略1: Stage 2 Monitor (`stage2_monitor.py` v4.0)

### 概述
基于 Stan Weinstein 和 Mark Minervini 的趋势模板理论，判断股票是否处于上升的"第二阶段"。这是其他策略的基础层。

### 8 个条件

| 条件 | 名称 | 判断标准 |
|------|------|----------|
| C1 | 价格位置 | 价格 > SMA150 且 > SMA200 |
| C2 | 均线排列 | SMA150 > SMA200 |
| C3 | 长期趋势 | SMA200 上升中（vs 20天前） |
| C4 | 短期均线 | SMA50 > SMA150 且 > SMA200 |
| C5 | 中期强度 | 价格 > SMA50 |
| C6 | 低点距离 | 价格 > 52周最低 × 1.25 |
| C7 | 高点距离 | 价格 > 52周最高 × 0.75 |
| C8 | 相对强度 | 6个月回报率 > SPY |

**判定规则**：8/8 条件全部满足 = Stage 2 确认

### 附加指标
- **Trend Power Score (0-100)**：综合评分，由均线排列紧密度(0-25)、价格位置(0-25)、52周位置(0-25)、相对强度(0-25) 四维度加权
- **成交量信号**：🔥放量 / 📈缩量上涨 / ⚠️放量回调 / 🔇缩量
- **动量**：5日/20日涨跌幅、SMA50 斜率

---

## 策略2: VCP Scanner (`vcp_scanner.py` v2.0)

### 概述
基于 Mark Minervini 的 VCP (Volatility Contraction Pattern) 理论。在已确认 Stage 2 的股票中，寻找波动率持续收缩、成交量枯竭、即将突破的标的。属于**右侧交易**。

### 前置依赖
- 必须先运行 `stage2_monitor.py`，VCP 从 DB 读取 `strategy_states` 表的 Stage 2 状态
- 仅分析 `is_active = true` 的 Stage 2 股票

### 6 个条件

| 条件 | 名称 | 参数 | 说明 |
|------|------|------|------|
| C1 | 52周回撤 | ≥ -25% | 距52周高点回撤不超过25% |
| C2 | 20日回撤 | ≥ -10% | 近期紧密盘整 |
| C3 | 布林带挤压 | BBW 分位 ≤ 25% | 过去120日中波动率处于底部25% |
| C4 | 成交量枯竭 | 10D/50D < 0.75 且 ≥4/5天缩量 | 卖压完全枯竭 |
| C5 | SMA50 斜率 | > 0% | 50日均线仍在上升 |
| C6 | 靠近 SMA10 | ±3% 以内 | 价格贴近短期均线 |

**判定规则**：≥ 4/6 条件满足 = VCP 信号

### VCP Score 评分 (0-100)

| 条件 | 权重 | 说明 |
|------|------|------|
| C1 | 15 | 52周位置 |
| C2 | 20 | 近期紧密度 |
| C3 | 25 | 布林带挤压（核心） |
| C4 | 20 | 成交量枯竭 |
| C5 | 10 | 趋势方向 |
| C6 | 10 | 价格收敛 |
| 加分 | +10 | BBW 分位 ≤ 10%（极度压缩） |
| 加分 | +5 | 5/5天全部缩量 |

---

## 策略3: Bottom Fisher (`bottom_fisher.py` v2.0)

### 概述
左侧抄底策略，寻找"好股票的坏价格"。与 VCP 互补——VCP 追涨已确认的上升趋势，Bottom Fisher 在下跌中寻找反转信号。通过四层递进判断，从质地过滤到K线确认，层层缩小候选范围。

### 扫描范围
全部 `tickers.json` 中 `enabled: true` 的 monitored 股票（不限于 Stage 2）。

### 四层递进指标体系

#### L1: 质地过滤（"值不值得抄？"）

| 条件 | 名称 | 参数 | 说明 |
|------|------|------|------|
| C1 | MA200 位置 | 价格在 MA200 的 -15% ~ +10% 范围内 | 长期趋势未完全破坏 |
| C2 | Stage 2 质地 | 当前/曾经 Stage 2，或快速检测 ≥4 个关键条件 | 只抄好股票的回调 |

#### L2: 跌幅充分（"跌够了吗？"）

| 条件 | 名称 | 参数 | 说明 |
|------|------|------|------|
| C3 | 52周回撤 | 距52周高点 ≤ -15% | 确保跌幅充分 |
| C4 | 20日回撤 | 距20日高点 ≤ -8% | 近期有明确下跌 |
| C5 | 支撑位 | 价格在 MA50/MA150/MA200 的 ±3% 内 | 有关键均线支撑 |

#### L3: 底部信号（"底部出现了吗？"）

| 条件 | 名称 | 参数 | 说明 |
|------|------|------|------|
| C6 | RSI 超卖/背离 | RSI(14) ≤ 35 或 RSI 底背离 | 动量超卖 |
| C7 | 成交量枯竭 | 10D均量/50D均量 < 0.6 | 卖压枯竭 |
| C8 | MACD 背离 | MACD 底背离或柱状图由负转正 | 动量拐头 |

#### L4: K线确认（加分项）

| 条件 | 名称 | 参数 | 说明 |
|------|------|------|------|
| B1 | 锤子线/十字星 | 实体 < 全幅30%，下影线 ≥ 实体2倍 | K线反转形态 |
| B2 | 放量确认 | 当日量 > 前日 × 1.5 | 买方入场确认 |

**判定规则**：≥ 5/8 条件（C1-C8）满足 = 抄底信号

### BF Score 评分 (0-100)

| 层级 | 条件 | 权重 |
|------|------|------|
| L1 质地 | C1(8) + C2(7) | 15 |
| L2 跌幅 | C3(10) + C4(10) + C5(15) | 35 |
| L3 底部 | C6(15) + C7(10) + C8(10) | 35 |
| L4 加分 | B1(+10) + B2(+5) | +15 |
| 特殊加分 | RSI背离 + MACD背离双确认 | +10 |

---

## 共享库 (lib/)

### `lib/db.py` — SQLite 数据访问层
- 单一 SQLite 文件 (`data/stock_tracker.db`)，WAL 模式
- 上下文管理器 `get_db()` 自动提交/回滚
- 所有 CRUD 操作集中管理，策略脚本零直接 SQL
- `get_prices_as_dataframe()` 返回兼容旧 CSV 格式的 pandas DataFrame
- Phase 5 新增：
  - `get_watchlist_item(symbol)` — 获取单个 watchlist 条目（含已禁用），用于 Web 添加时检查是否曾存在
  - `set_ticker_enabled(symbol, enabled)` — 设置 ticker 启用/禁用状态（软删除/恢复）
  - `get_price_count(symbol)` — 获取价格记录数，判断恢复时是否需要重新拉取数据

### `lib/config.py` — 配置加载 & 观察列表同步
- 从 `config/tickers.json` 读取配置
- `sync_watchlist()` 幂等同步到数据库 `watchlist` 表
- `get_monitored_tickers()` / `get_yfinance_tickers()` 按分组获取

### `lib/indicators.py` — 共享技术指标库
从各策略脚本中提取的公共技术指标函数，避免重复代码：

| 指标 | 函数 |
|------|------|
| SMA / EMA | `sma()`, `ema()` |
| RSI (Wilder 平滑) | `rsi()` |
| MACD | `macd()` → (line, signal, histogram) |
| ATR | `atr()` |
| 布林带宽度 | `bollinger_bandwidth()`, `bbw_percentile()` |
| 连涨连跌 | `consecutive_streak()` |
| RSI 底背离 | `detect_rsi_divergence()` |
| MACD 底背离 | `detect_macd_divergence()` |
| K线形态 | `detect_hammer()`（锤子线/十字星） |
| 涨跌幅 | `pct_change()`, `pct_from_value()` |
| 时区工具 | `normalize_tz()` |

### `lib/models.py` — 数据模型定义
使用 Python `dataclass` 定义各策略的输入/输出结构，提供 `to_db_dict()` 和 `from_db_row()` 双向转换：

- `TickerInfo` — 观察列表中的股票信息
- `StrategyResult` — 策略结果基类
- `Stage2Result` / `VCPResult` / `BottomFisherResult` — 策略特化结果
- `MarketPulseResult` — 市场宏观状态
- `SignalChange` — 信号变化事件

### `lib/report.py` — 报告生成共享工具
- Jinja2 环境管理，加载 `templates/*.j2` 模板
- 自定义过滤器：`tg_escape`、`score_emoji_*`、`chg_emoji`、`score_bar`、`progress_bar`、`fmt_pct`、`fmt_price`、`fmt_val`
- `split_telegram_message()` — 按段落边界分割长消息（Telegram 4000 字符限制）
- `save_reports()` — 统一保存 MD + Telegram HTML + manifest

### `lib/pipeline.py` — Web 单 Ticker 管道（Phase 5 新增）

Web 添加 ticker 时使用的完整处理管道，由两个核心函数组成：

#### `validate_ticker(symbol)` — 三层验证

| 层级 | 方法 | 耗时 | 说明 |
|------|------|------|------|
| L1 | 正则格式校验 | ~0ms | 1-5 个大写字母，可带 `.A`/`.B` 后缀 |
| L2 | `yf.Ticker(s).info` 元数据检查 | ~1s | 确认 `shortName`/`longName` 存在 |
| L3 | 试拉 5 天历史数据 | ~1s | 确认数据源可用，非极新 IPO |

返回包含 `valid`、`name`、`sector`、`exchange`、`market_price` 等元数据的验证结果。

#### `run_single_ticker_pipeline(symbol, name, sector)` — 完整策略管道

| 步骤 | 操作 | 说明 |
|------|------|------|
| Step 1 | 拉取 365 天历史价格（yfinance）→ `upsert_prices()` | 价格数据入库 |
| Step 2 | 运行 Stage 2 分析 → `save_strategy_result()` + `upsert_strategy_state()` | 趋势确认 |
| Step 3 | 运行 VCP 分析（仅当 Stage 2 active） | 右侧追涨 |
| Step 4 | 运行 Bottom Fisher 分析 | 左侧抄底 |

**特殊处理**：管道使用当天日期 (`datetime.now()`) 作为策略结果的 `date_str`，这可能与批量 cron 产生的 `market_pulse.latest_date` 不同。Web 端（watchlist/ticker/API）通过 **fallback 查询**机制解决此日期不匹配问题——当按 `latest_date` 查不到策略结果时，回退查询该 ticker 最新的一条结果。

---

## Jinja2 报告模板 (templates/)

每个策略各有 Markdown 存档和 Telegram 推送两种格式：

| 模板文件 | 用途 |
|----------|------|
| `stage2_md.j2` | Stage 2 报告 Markdown 版 |
| `stage2_tg.j2` | Stage 2 报告 Telegram HTML 版 |
| `vcp_md.j2` | VCP 扫描报告 Markdown 版 |
| `vcp_tg.j2` | VCP 扫描报告 Telegram HTML 版 |
| `bottom_md.j2` | 抄底信号报告 Markdown 版 |
| `bottom_tg.j2` | 抄底信号报告 Telegram HTML 版 |
| `pulse_md.j2` | 市场脉搏报告 Markdown 版 |
| `pulse_tg.j2` | 市场脉搏报告 Telegram HTML 版 |

---

## 使用方式

### 首次安装

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 初始化数据库
python -m lib.db init

# 3. 同步观察列表
python lib/config.py

# 4. 从旧项目迁移数据（可选）
python scripts/migrate_prices.py --source D:/eh/projects/workspace/stocks
```

### 日常运行

```bash
# 数据采集
python scripts/save_prices_yfinance.py     # yfinance（全部股票）

# 四个策略逐个运行
python scripts/market_pulse.py             # 市场温度计
python scripts/stage2_monitor.py           # Stage 2 趋势确认
python scripts/vcp_scanner.py              # VCP 择时信号
python scripts/bottom_fisher.py            # 抄底信号扫描

# 静默模式（模拟 cron 行为，压制 stdout）
python scripts/market_pulse.py --cron
python scripts/stage2_monitor.py --cron
python scripts/vcp_scanner.py --cron
python scripts/bottom_fisher.py --cron
```

### 命令行参数

| 脚本 | 参数 | 说明 |
|------|------|------|
| `save_prices_yfinance.py` | `--mode all\|yfinance_only` | 数据拉取范围（默认 all） |
| `save_prices_yfinance.py` | `--test TICKER` | 测试单只 ticker |
| `save_prices_yfinance.py` | `--no-csv` | 不保存 CSV 备份 |
| `market_pulse.py` | `--cron` | 压制 stdout 输出 |
| `stage2_monitor.py` | `--cron` | 压制 stdout 输出 |
| `vcp_scanner.py` | `--cron` | 压制 stdout 输出 |
| `bottom_fisher.py` | `--cron` | 压制 stdout 输出 |

### 数据库工具

```bash
python -m lib.db init    # 初始化数据库（幂等）
python -m lib.db stats   # 查看数据库统计信息
```

---

## 目录结构

```
stock-tracker/
├── config/
│   └── tickers.json              # 监控股票列表
├── data/
│   ├── stock_tracker.db          # SQLite 数据库（.gitignore）
│   └── prices/                   # CSV 备份缓存（.gitignore）
├── lib/
│   ├── __init__.py               # 包初始化
│   ├── config.py                 # 配置加载 & watchlist 同步
│   ├── db.py                     # SQLite 数据访问层（~800行，项目核心）
│   ├── indicators.py             # 共享技术指标库
│   ├── models.py                 # 数据模型（dataclass）
│   ├── pipeline.py               # Web 单 Ticker 管道（验证 + 拉取 + 策略）
│   └── report.py                 # 报告生成共享工具（Jinja2）
├── templates/
│   ├── stage2_md.j2 / stage2_tg.j2
│   ├── vcp_md.j2 / vcp_tg.j2
│   ├── bottom_md.j2 / bottom_tg.j2
│   └── pulse_md.j2 / pulse_tg.j2
├── scripts/
│   ├── save_prices.py            # ⚠️ 已弃用（Stooq 数据源不可用）
│   ├── save_prices_yfinance.py   # 数据采集 v2.0（yfinance + SQLite）
│   ├── market_pulse.py           # 策略0: 市场温度计 v3.0
│   ├── stage2_monitor.py         # 策略1: Stage 2 趋势确认 v4.0
│   ├── vcp_scanner.py            # 策略2: VCP 右侧追涨 v2.0
│   ├── bottom_fisher.py          # 策略3: 抄底左侧信号 v2.0
│   └── migrate_prices.py         # 数据迁移工具（CSV/JSON → SQLite）
├── reports/
│   └── daily/                    # 每日报告存档（.md + .html + manifest）
├── web/                          # Phase 4: Web Dashboard
│   ├── app.py                    # FastAPI 主入口
│   ├── deps.py                   # Jinja2 模板 + 过滤器
│   ├── routes/                   # 路由（dashboard/watchlist/ticker/api）
│   ├── templates/                # HTML 模板（base/dashboard/watchlist/detail）
│   └── static/                   # CSS（深色主题）+ JS（排序/筛选）
├── logs/                         # 日志文件（.gitignore）
├── requirements.txt              # Python 依赖
├── .gitignore
└── README.md                     # 本文档
```

---

## Pipeline 执行顺序

```bash
# 推荐的完整执行顺序：
Step 1:  python scripts/save_prices_yfinance.py  # yfinance 数据采集
Step 2:  python scripts/market_pulse.py --cron    # 市场温度计
Step 3:  python scripts/stage2_monitor.py --cron  # Stage 2 趋势确认
Step 4:  python scripts/vcp_scanner.py --cron     # VCP 择时信号
Step 5:  python scripts/bottom_fisher.py --cron   # 抄底信号扫描
```

- Step 1 失败不影响后续步骤（Market Pulse 会优雅降级）
- Step 2 (Market Pulse) 最先推送，先看全局再看个股
- Step 4 (VCP) 依赖 Step 3 (Stage 2) 成功运行
- Step 5 (Bottom Fisher) 独立运行，不依赖 Stage 2 结果
- 每步失败不影响后续步骤（除 VCP 依赖 Stage 2）

---

## 参数调优指南

所有策略参数均集中在各 Python 脚本顶部的 `*_PARAMS` 字典中，修改后立即生效。

### VCP Scanner 关键参数

```python
VCP_PARAMS = {
    "bbw_percentile_threshold": 25,   # ↓ 更严格（如15），↑ 更宽松（如35）
    "vol_ratio_threshold": 0.75,      # ↓ 要求更极致缩量
    "strong_signal_min": 4,           # ↑ 减少信号，↓ 增加信号
}
```

### Bottom Fisher 关键参数

```python
BF_PARAMS = {
    "min_drawdown_from_52w_high": -15,  # ↑ 不需要跌很多，↓ 要求跌更深
    "rsi_oversold": 35,                 # ↑ 更宽松，↓ 只抓极端超卖
    "vol_ratio_threshold": 0.6,         # ↑ 更宽松，↓ 要求更极致缩量
    "support_proximity_pct": 3.0,       # ↑ 支撑判断更宽松
    "strong_signal_min": 5,             # ↑ 减少信号，↓ 增加信号
}
```

---

## 依赖

| 依赖 | 版本 | 用途 |
|------|------|------|
| `pandas` | ≥ 2.0.0 | 核心数据处理 |
| `numpy` | ≥ 1.24.0 | 数值计算 |
| `yfinance` | ≥ 0.2.30 | Yahoo Finance 数据源 |
| `pandas-datareader` | ≥ 0.10.0 | 辅助数据获取 |
| `jinja2` | ≥ 3.1.0 | 模板引擎 |
| *SQLite* | *内置* | 数据库（Python 标准库） |
| `fastapi` | ≥ 0.100.0 | Web 框架 (Phase 4) |
| `uvicorn` | ≥ 0.23.0 | ASGI 服务器 (Phase 4) |

---

## Phase 4: Web Dashboard

### 概述

基于 FastAPI + Jinja2 SSR + Chart.js 的本地 Web Dashboard，提供三个核心页面，复用 Phase 1-3 的全部 `lib/db.py` 查询 API，零数据库改造。

### 启动方式

```bash
# 方式一：直接启动
python -m web.app

# 方式二：使用 uvicorn（支持热重载）
uvicorn web.app:app --reload --port 8000

# 打开浏览器访问
# http://127.0.0.1:8000
```

> 📖 **完整部署指南**（含 Linux 服务器 / Oracle Cloud / 域名配置 / HTTPS）请参见 [DEPLOY.md](DEPLOY.md)

### 三个核心页面

| 页面 | 路径 | 功能 |
|------|------|------|
| **Dashboard** | `/` | Market Pulse 状态 + 三策略信号摘要 + 近期信号变化 + 30天走势图 |
| **Watchlist** | `/watchlist` | 全部监控股票的多策略横向对照表，支持板块筛选/搜索/仅信号过滤 + **Ticker 新增/删除** |
| **Ticker Detail** | `/ticker/{symbol}` | 个股三策略状态卡片 + 条件明细 + 关键指标 + 信号历史 + Score 走势图 |

### Web Ticker 管理（Phase 5 新增）

通过 Watchlist 页面的 **"➕ 添加 Ticker"** 按钮和每行的 **"×" 移除按钮**，直接在 Web 上管理观察列表，无需编辑 `tickers.json`。

#### 添加流程

```
用户输入 Ticker → 点击"验证" → yfinance 三层验证 → 显示元数据（名称/板块/价格）
                                                          ↓
                              点击"添加到观察列表" → 写入 watchlist 表
                                                          ↓
                              run_single_ticker_pipeline() → 拉取价格 + 跑全部策略
                                                          ↓
                                                   页面自动刷新 → 展示完整数据
```

**特殊情况处理**：
- **已存在且启用** → 提示已在列表中，阻止重复添加
- **曾被移除（enabled=0）** → 提示可恢复，恢复后复用已有数据或重新拉取
- **全新 Ticker** → 完整验证 + 管道执行

#### 删除方式

**软删除**（`enabled=0`），不物理删除任何数据。后续可通过"添加"操作恢复显示。

### API 端点

| 端点 | 说明 |
|------|------|
| `GET /api/tickers/check/{symbol}` | **Phase 5** 验证 ticker（三层验证 + 已存在检查） |
| `POST /api/tickers` | **Phase 5** 新增 ticker（验证 → 写入 watchlist → 运行策略管道） |
| `DELETE /api/tickers/{symbol}` | **Phase 5** 软删除 ticker（设 `enabled=0`，不删数据） |
| `GET /api/dashboard` | Dashboard 全量数据 JSON |
| `GET /api/market-pulse/latest` | 最新 Market Pulse |
| `GET /api/market-pulse/history?days=30` | Market Pulse 历史走势 |
| `GET /api/signals/recent?limit=20` | 近期信号变化 |
| `GET /api/ticker/{symbol}` | 个股策略数据 |
| `GET /api/ticker/{symbol}/history?strategy=stage2&days=30` | 个股策略历史 |

### 技术栈

| 组件 | 选型 | 说明 |
|------|------|------|
| 后端 | FastAPI + Uvicorn | 高性能 ASGI 框架 |
| 模板 | Jinja2 SSR | 服务端渲染，复用 Phase 3 能力 |
| 样式 | 手写 CSS（深色主题） | 金融工具标配，护眼 |
| 图表 | Chart.js (CDN) | 轻量折线图 |
| 交互 | Vanilla JS | 客户端表格排序/筛选 + Ticker 管理（Modal + Fetch API） |
| 数据管道 | lib/pipeline.py | 单 Ticker 验证 + 拉取 + 策略分析（Phase 5） |

### Web 目录结构

```
web/
├── __init__.py
├── app.py                    # FastAPI 主入口
├── deps.py                   # Jinja2 模板引擎 + 自定义过滤器
├── routes/
│   ├── __init__.py
│   ├── dashboard.py          # Dashboard 首页路由
│   ├── watchlist.py          # Watchlist 列表路由（含 fallback 查询）
│   ├── ticker.py             # Ticker Detail 详情路由（含 fallback 查询）
│   └── api.py                # JSON API（含 Ticker 管理 CRUD + fallback 查询）
├── templates/
│   ├── base.html             # 基础布局（导航 + 页脚 + Modal Overlay）
│   ├── dashboard.html        # Dashboard 页面
│   ├── watchlist.html        # Watchlist 页面（含添加 Ticker 弹窗 + 移除按钮）
│   └── ticker_detail.html    # Ticker Detail 页面
└── static/
    ├── css/style.css         # 深色主题样式（含 Modal + 验证状态样式）
    └── js/main.js            # 表格排序/筛选 + Ticker 验证/添加/移除交互逻辑
```
