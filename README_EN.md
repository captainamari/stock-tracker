# 📊 Stock Tracker — US Stock Technical Analysis & Signal Monitoring System

An automated US stock analysis pipeline built on Stan Weinstein's stage analysis, Mark Minervini's trend template / VCP theory, and multi-dimensional quantitative bottom-fishing models.

## Overview

```
save_prices.py            → Data collection ⚠️ Deprecated (Stooq unavailable)
save_prices_yfinance.py   → Data collection yfinance (incremental + auto-chain strategies/Market Pulse)
        ↓
    SQLite DB (stock_tracker.db)
        ↓
market_pulse.py           → Strategy 0: Market Thermometer (macro overview + Distribution Day detection, pushed first)
        ↓
stage2_monitor.py         → Strategy 1: Stage 2 Trend Confirmation (foundation)
        ↓
vcp_scanner.py            → Strategy 2: VCP Breakout (depends on Stage 2)
bottom_fisher.py          → Strategy 3: Bottom-Fishing Signal (independent)
buying_checklist.py       → Strategy 4: Buying Checklist (multi-dimensional, weekly Elder Impulse)
        ↓
    Jinja2 Templates → reports/daily/ (MD + Telegram HTML)
        ↓
    web/app.py               → Phase 4: Web Dashboard (FastAPI + Chart.js)
        ↓
    lib/pipeline.py           → Phase 5: Web Ticker Management (validate + fetch + pipeline + auto Market Pulse)
```

### Strategy Comparison

| Dimension | Market Pulse | Stage 2 Monitor | VCP Scanner | Bottom Fisher | Buying Checklist |
|-----------|-------------|----------------|-------------|---------------|-----------------|
| **Theory** | Multi-dim market thermometer + IBD Distribution Day | Stan Weinstein 4 stages | Mark Minervini VCP | Technical bottom (mean reversion) | Elder Impulse + multi-dim checklist |
| **Direction** | Macro assessment | Trend confirmation | Right-side breakout | Left-side reversal | Comprehensive buy decision |
| **Scope** | SPY/QQQ/IWM/VIX + full pool | All monitored | Stage 2 only | All monitored | All monitored |
| **Core question** | "Offense or defense?" | "Is it in an uptrend?" | "Which is about to break out?" | "Which good stock has bottomed?" | "Is it time to buy?" |
| **Signal** | 🟢Offense/🟡Caution/🟠Defense/🔴Cash | Healthy → hold | Contraction → breakout | Oversold → buy window | Multi-confirmed → buy |

---

## Project Roadmap

| Phase | Description | Status |
|-------|-------------|--------|
| Phase 1 | Standalone project + DB schema + `lib/db.py` + migration scripts (CSV→DB) | ✅ Done |
| Phase 2 | Refactor strategies to store results in DB + dual-write transition | ✅ Done |
| Phase 3 | Extract Jinja2 report templates, render from DB data | ✅ Done |
| Phase 4 | Web app (Dashboard + Watchlist + Ticker Detail) | ✅ Done |
| Phase 5 | Web Ticker management (validate + add + remove + single-ticker pipeline) | ✅ Done |
| Phase 6 | i18n + Technical Analysis module + page layout optimization | ✅ Done |

---

## Architecture

### System Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                     config/tickers.json                       │
│              Stocks + Index/ETF + SPY Benchmark               │
└───────────────────────────┬──────────────────────────────────┘
                            │
         ┌──────────────────┼──────────────────┐
         ▼                  ▼                  ▼
  save_prices.py     save_prices_yfinance.py   lib/config.py
  (Stooq → stocks)   (yfinance → VIX/QQQ/IWM)  (sync_watchlist)
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
     Strategy scripts   lib/indicators.py     lib/models.py
     (scripts/*.py)     (shared indicators)   (data models)
           │                                      │
           ▼                                      ▼
     lib/report.py + templates/*.j2         lib/pipeline.py
           │                               (Web single-ticker pipeline)
           ▼
     reports/daily/ (MD + Telegram HTML + manifest)
```

### Database Schema (7 tables)

| Table | Purpose | Primary Key |
|-------|---------|-------------|
| `watchlist` | Watch list (synced from tickers.json) | symbol |
| `stock_prices` | Daily OHLCV price data | (symbol, date) |
| `strategy_results` | Strategy daily results (shared by all) | (symbol, date, strategy) |
| `strategy_states` | Strategy current state tracking | (symbol, strategy) |
| `signal_changes` | Signal entry/exit history | id (auto-increment) |
| `market_pulse` | Market macro state (incl. Distribution Day data) | date |
| `db_meta` | Database version metadata | key |

**Design highlights**:
- `strategy_results` uses JSON columns (`conditions`, `condition_details`, `metrics`) for flexible strategy-specific data
- `market_pulse` table includes `distribution_days` JSON column storing SPY/QQQ Distribution Day detailed data
- SQLite WAL mode for improved concurrent read performance
- `_NumpyEncoder` auto-handles numpy type JSON serialization

### Data Flow

```
tickers.json
     │
     ├── monitored[] + benchmark ──→ save_prices.py (Stooq)
     │                                     │
     ├── yfinance_only[] ────────→ save_prices_yfinance.py (incremental)
     │                                     │
     │    ┌────────────────────────────────┘
     │    │              Write to stock_prices table
     │    │              (incremental update, fetch new data only)
     │    │
     │    │  ┌─── Auto-chained after price update ──────────────┐
     │    │  │                                                    │
     ▼    ▼  ▼                                                    │
market_pulse.py  ──→  market_pulse table  (SPY+QQQ+IWM+VIX+breadth+Distribution Days)│
     │                                                            │
stage2_monitor.py  ──→  strategy_results/states                   │
     │                        │                                   │
     │                        ▼                                   │
     │                  vcp_scanner.py  ──→  strategy_results/states
     │                                                            │
     ├──────────────→  bottom_fisher.py  ──→  strategy_results/states
     │                                                            │
     ├──────────────→  buying_checklist.py  ──→  strategy_results/states
     │                                                            │
     └──────────────→  [Phase 4] Web Dashboard ←──────────────────┘
                       (auto fallback on date mismatch)
```

---

## Data Collection Layer

### `save_prices.py` — Stooq Data Source

Primary data collection script, fetches OHLCV daily data from stooq.com, covering stocks + SPY benchmark in `tickers.json`.

### `save_prices_yfinance.py` — yfinance (v2.1 Incremental Mode)

Supplementary script, fetches tickers not covered by Stooq from Yahoo Finance, reads `yfinance_only` section.

**v2.1 improvements**:
- **Incremental check**: Queries DB for latest price date per ticker; skips if today's data exists, otherwise fetches incremental data only
- **Auto-run strategies**: After price update, automatically runs all strategy calculations (Stage 2 / VCP / Bottom Fisher / Buying Checklist)
- **Auto-update Market Pulse**: After strategies complete, automatically runs Market Pulse analysis, ensuring date consistency

| Comparison | Stooq | yfinance |
|-----------|-------|----------|
| **Coverage** | Stocks + SPY | VIX / SPY / QQQ / IWM |
| **Config** | `monitored[]` + `benchmark` | `yfinance_only[]` |
| **Interval** | 1 sec | 2~3.5 sec (conservative) |
| **Risk** | Unlimited flow | Rate-limiting risk |
| **Storage** | SQLite DB + CSV | SQLite DB + CSV |
| **Fetch mode** | Full 365 days | Incremental (new only) |
| **Chaining** | None | Auto strategies + Market Pulse |

> ⚠️ Stooq is the primary source due to yfinance's severe rate limiting and IP ban risk. yfinance is only used for supplementary tickers.

---

## Strategy 0: Market Pulse (`market_pulse.py` v4.0)

### Overview
Market macro thermometer. Combines SPY/QQQ/IWM trends + VIX fear index + internal breadth + sector heat + **Distribution Day analysis (IBD methodology)**. **Pushed before all individual strategies** — big picture first, then individual signals.

### Design Principles
- Reads DB data only, zero network requests
- Graceful degradation when data unavailable (missing VIX → auto weight redistribution)

### 6 Analysis Modules

#### ① SPY Trend Analysis (Weight 30%)

| Indicator | Score | Description |
|-----------|-------|-------------|
| Price > SMA50 | +10 | Short-term trend up |
| Price > SMA200 | +10 | Long-term trend up |
| SMA50 > SMA200 (Golden Cross) | +10 | Healthy MA alignment |
| SMA200 rising | +5 | Long-term acceleration |
| Price > EMA65 | +5 | Simulated weekly trend |
| Weekly alignment (EMA65 > EMA170) | +5 | Weekly-level healthy |
| MACD > 0 | +8 | Positive momentum |
| MACD histogram rising | +7 | Accelerating momentum |
| Short-term (EMA8 > EMA21) | +5 | Short-term positive |
| 5-day momentum > 0 | +3~10 | Recent positive |
| RSI healthy (40-70) | +10 | Neither overbought nor oversold |
| Within 5% of 52W high | +10 | Near new highs |
| EMA170 rising | +5 | Long-term confirmation |

#### ② QQQ Trend Analysis (Weight 15%)
Same scoring as SPY. Represents NASDAQ tech direction.

#### ③ IWM Trend Analysis (Weight 10%)
Same scoring as SPY. Represents small-cap sentiment (risk appetite).

#### ④ VIX Fear Analysis (Weight 25%)

| VIX Range | Status | Score |
|-----------|--------|-------|
| < 12 | Extremely Optimistic 😎 | 100 |
| 12-15 | Optimistic | 85 |
| 15-18 | Normal | 70 |
| 18-22 | Elevated 😟 | 55 |
| 22-25 | Fearful 😨 | 40 |
| 25-30 | High Fear | 25 |
| 30-35 | Extreme Fear 🤯 | 10 |
| ≥ 35 | Panic | 0 |

#### ⑤ Internal Breadth Analysis (Weight 20%)

Based on monitored pool (not entire market):

| Indicator | Max Score | Description |
|-----------|----------|-------------|
| Price > MA50 ratio | 35 | Short-term participation |
| Price > MA200 ratio | 25 | Long-term health |
| Stage 2 ratio | 25 | Trend confirmation density |
| 5-day up ratio | 15 | Immediate momentum |

Additional: Sector heat ranking (sorted by Stage 2 ratio).

### ⑥ Distribution Day Analysis (IBD Methodology)

Based on Investor's Business Daily (IBD) classic market health indicator, detecting institutional selling at the index level. Historically, 5+ distribution days in a 25-day window often precede significant market declines.

#### Distribution Day Definition

| Type | Trigger | Description |
|------|---------|-------------|
| **Distribution Day** | Index drops ≥ 0.2% on higher volume than previous day | Institutions selling on heavy volume |
| **Stalling Day** | Index closes up slightly (< 0.4%) in upper 75% of range, on higher volume | Institutions selling into strength (churning) |

#### Rolling Window & Expiration Rules

| Rule | Parameter | Description |
|------|-----------|-------------|
| Rolling window | 25 trading days | Only counts distribution days within last 25 sessions |
| Time expiration | > 25 trading days | Auto-expires after 25 trading days |
| Rally expiration | Index rallies ≥ 5% from that day's close | Market recovered, that day no longer counts |

#### 5-Level Warning System

| Cumulative Pressure* | Level | Emoji | Description |
|----------------------|-------|-------|-------------|
| < 2 | Low | ✅ | Normal, no significant selling |
| 2-3 | Moderate | 🟡 | Light selling, monitor closely |
| 4 | Elevated | 🟠 | Increased selling, heighten awareness |
| 5 | High | 🔴 | Heavy selling, reduce exposure signal |
| ≥ 6 | Extreme | 🚨 | Extreme selling, very high correction risk |

*Cumulative Pressure = Distribution Days + Stalling Days × 0.5

#### Scope
- **SPY** (S&P 500) and **QQQ** (Nasdaq 100) tracked independently
- Data source: Existing index daily OHLCV data in DB

### Composite Score & Market State

| Score | State | Emoji | Suggestion |
|-------|-------|-------|------------|
| ≥ 70 | BULLISH — Offense | 🟢 | Actively seek Stage 2 + VCP entries |
| 50-69 | NEUTRAL — Caution | 🟡 | Direction unclear, control size, wait |
| 35-49 | CAUTIOUS — Defense | 🟠 | Weak market, reduce new positions |
| < 35 | BEARISH — Cash | 🔴 | Downtrend, cash is king |

**Special rules**:
- VIX ≥ 30 → Force 🔴 BEARISH (pause all buying on fear spike)
- SPY below SMA200 by >3% → Max downgrade to 🟠 CAUTIOUS
- VIX < 13 and BULLISH → Attach ⚠️ complacency warning
- **Distribution Days ≥ 6** → Force downgrade to 🔴 BEARISH (heavy institutional selling — cash is king)
- **Distribution Days ≥ 5** → Max downgrade to 🟠 CAUTIOUS (elevated selling — reduce exposure)
- **Distribution Days ≥ 4 and BULLISH** → Attach ⚠️ distribution days rising warning

### Regime Change Detection
Auto-detects state changes. On regime switch (e.g., 🟢→🟡), Telegram push highlights the change at the top.

---

## Strategy 1: Stage 2 Monitor (`stage2_monitor.py` v4.0)

### Overview
Based on Stan Weinstein and Mark Minervini's trend template theory, determines if a stock is in the rising "Stage 2". Foundation for other strategies.

### 8 Conditions

| # | Name | Criteria |
|---|------|----------|
| C1 | Price position | Price > SMA150 and > SMA200 |
| C2 | MA alignment | SMA150 > SMA200 |
| C3 | Long-term trend | SMA200 rising (vs 20 days ago) |
| C4 | Short-term MA | SMA50 > SMA150 and > SMA200 |
| C5 | Mid-term strength | Price > SMA50 |
| C6 | Low distance | Price > 52W low × 1.25 |
| C7 | High distance | Price > 52W high × 0.75 |
| C8 | Relative strength | 6-month return > SPY |

**Rule**: 8/8 met = Stage 2 confirmed

### Additional Indicators
- **Trend Power Score (0-100)**: MA tightness (0-25) + price position (0-25) + 52W position (0-25) + relative strength (0-25)
- **Volume signal**: 🔥 Heavy / 📈 Low-vol rise / ⚠️ Heavy pullback / 🔇 Low
- **Momentum**: 5D/20D change, SMA50 slope

---

## Strategy 2: VCP Scanner (`vcp_scanner.py` v2.0)

### Overview
Mark Minervini's VCP (Volatility Contraction Pattern). Scans confirmed Stage 2 stocks for contracting volatility, exhausted volume, and imminent breakout. **Right-side trade**.

### Prerequisites
- Must run `stage2_monitor.py` first; VCP reads Stage 2 state from `strategy_states`
- Only analyzes `is_active = true` Stage 2 stocks

### 6 Conditions

| # | Name | Parameter | Description |
|---|------|-----------|-------------|
| C1 | 52W drawdown | ≥ -25% | Within 25% of 52W high |
| C2 | 20D drawdown | ≥ -10% | Recent tight consolidation |
| C3 | Bollinger squeeze | BBW pctl ≤ 25% | Bottom 25% volatility over 120 days |
| C4 | Volume exhaustion | 10D/50D < 0.75, ≥4/5 low-vol days | Selling completely exhausted |
| C5 | SMA50 slope | > 0% | 50-day MA still rising |
| C6 | Near SMA10 | Within ±3% | Price hugging short-term MA |

**Rule**: ≥ 4/6 met = VCP signal

### VCP Score (0-100)

| Condition | Weight | Description |
|-----------|--------|-------------|
| C1 | 15 | 52W position |
| C2 | 20 | Recent tightness |
| C3 | 25 | Bollinger squeeze (core) |
| C4 | 20 | Volume exhaustion |
| C5 | 10 | Trend direction |
| C6 | 10 | Price convergence |
| Bonus | +10 | BBW pctl ≤ 10% (extreme) |
| Bonus | +5 | All 5/5 days low volume |

---

## Strategy 3: Bottom Fisher (`bottom_fisher.py` v2.0)

### Overview
Left-side reversal strategy, searching for "good stocks at bad prices". Complementary to VCP. Four-layer progressive filter from quality to candlestick confirmation.

### Scan Scope
All `enabled: true` monitored stocks (not limited to Stage 2).

### Four-Layer System

#### L1: Quality Filter ("Worth bottom-fishing?")

| # | Name | Parameter | Description |
|---|------|-----------|-------------|
| C1 | MA200 position | Price within -15%~+10% of MA200 | Long-term trend not broken |
| C2 | Stage 2 quality | Current/former Stage 2, or ≥4 key conditions | Only fish quality pullbacks |

#### L2: Sufficient Decline ("Dropped enough?")

| # | Name | Parameter | Description |
|---|------|-----------|-------------|
| C3 | 52W drawdown | ≤ -15% from 52W high | Sufficient decline |
| C4 | 20D drawdown | ≤ -8% from 20D high | Clear recent decline |
| C5 | Support | Price within ±3% of MA50/MA150/MA200 | Key MA support |

#### L3: Bottom Signals ("Is bottom forming?")

| # | Name | Parameter | Description |
|---|------|-----------|-------------|
| C6 | RSI oversold/divergence | RSI(14) ≤ 35 or RSI divergence | Momentum oversold |
| C7 | Volume exhaustion | 10D/50D avg vol < 0.6 | Selling exhausted |
| C8 | MACD divergence | Bullish divergence or histogram turns positive | Momentum turning |

#### L4: Candlestick Confirmation (Bonus)

| # | Name | Parameter | Description |
|---|------|-----------|-------------|
| B1 | Hammer/Doji | Body < 30% range, lower shadow ≥ 2× body | Reversal pattern |
| B2 | Volume confirm | Volume > yesterday × 1.5 | Buyer entry |

**Rule**: ≥ 5/8 (C1-C8) met = Bottom-fishing signal

### BF Score (0-100)

| Layer | Conditions | Weight |
|-------|-----------|--------|
| L1 Quality | C1(8) + C2(7) | 15 |
| L2 Decline | C3(10) + C4(10) + C5(15) | 35 |
| L3 Bottom | C6(15) + C7(10) + C8(10) | 35 |
| L4 Bonus | B1(+10) + B2(+5) | +15 |
| Special | RSI + MACD divergence double confirmation | +10 |

---

## Strategy 4: Buying Checklist (`buying_checklist.py` v1.0)

### Overview
Multi-dimensional buying checklist combining trend, momentum, volume, and patterns. **Not an independent signal generator, but the "ultimate confirmation" layer** — after other strategies give direction, it answers "Is it really time to buy?"

### Scan Scope
All `enabled: true` monitored stocks.

### Five-Layer Checklist

#### L1: Trend Confirmation ("Right direction?")

| # | Name | Description |
|---|------|-------------|
| C1 | Weekly Elder Impulse | Green (trend + momentum both up) |
| C2 | Daily MA alignment | EMA8 > EMA21 > EMA50 |
| C3 | Above SMA50 | Short-term support effective |

#### L2: Momentum Health ("Strong enough?")

| # | Name | Description |
|---|------|-------------|
| C4 | RSI healthy zone | RSI(14) in 50-70 (strong, not overbought) |
| C5 | MACD positive | Histogram > 0 or turning up |

#### L3: Price Structure ("Reasonable position?")

| # | Name | Description |
|---|------|-------------|
| C6 | 52W distance | Drawdown within -25% |
| C7 | MA support | Price near key MAs (MA20/MA50) |

#### L4: Volume Confirmation ("Volume confirming?")

| # | Name | Description |
|---|------|-------------|
| C8 | Volume-price alignment | Rising on higher volume or breakout confirmation |

#### L5: Composite Bonus ("Cherry on top?")

| # | Name | Description |
|---|------|-------------|
| B1 | Multi-strategy confluence | Stage 2 + VCP or Stage 2 + Bottom Fisher simultaneously |
| B2 | Candlestick pattern | Hammer/Doji reversal or breakout patterns |

**Rule**: Composite score reaches threshold = Buy check passed

### BC Score (0-100)

| Layer | Weight | Description |
|-------|--------|-------------|
| L1 Trend | 25 | Elder Impulse + MA alignment |
| L2 Momentum | 20 | RSI + MACD |
| L3 Structure | 20 | Price position + MA support |
| L4 Volume | 15 | Volume confirmation |
| L5 Bonus | +20 | Strategy confluence + patterns |

---

## Technical Analysis Module (`lib/technical_analysis.py`)

### Overview
Four major technical analysis systems for the Ticker Detail page, generating comprehensive reports per stock. Reuses `lib/indicators.py` base functions.

### Four Systems

#### ① Moving Average System

| Item | Description |
|------|-------------|
| MA values | SMA5 / SMA20 / SMA50 / SMA100 / SMA200 |
| Price position | above/below each MA |
| MA arrangement | Bullish / Bearish / Mixed |
| Golden/Death Cross | SMA5 vs SMA20 crossover |
| EMA | EMA12 / EMA26 auxiliary |

#### ② Momentum Indicators

| Indicator | Parameters | Description |
|-----------|-----------|-------------|
| RSI | RSI(14) | Overbought/oversold/healthy zone |
| Stochastic | K(14,3) / D(3) | Crossover signals |
| MACD | (12,26,9) | Zero line + signal + histogram |
| ADX | ADX(14) | Trend strength (strong/weak/ranging) |
| HV30 | 30-day vol | Annualized volatility % |

#### ③ Support & Resistance

| Item | Description |
|------|-------------|
| Bollinger Bands | Upper/mid/lower + bandwidth + position (overbought/near/oversold) |
| VWAP | 20-day volume-weighted average |
| Statistical range | 30D high/low + position % |
| 52W range | High/low + distance from high |
| Key levels | Combined MA + Bollinger + statistical extremes |

#### ④ Fibonacci Retracement & Extension

| Item | Description |
|------|-------------|
| Swing detection | Auto-detect recent swing high / swing low |
| Retracement | 23.6% / 38.2% / 50% / 61.8% / 78.6% |
| Extension | 127.2% / 161.8% / 200% / 261.8% |
| Current position | Which zone price is in |

---

## Shared Library (lib/)

### `lib/db.py` — SQLite Data Access Layer
- Single SQLite file (`data/stock_tracker.db`), WAL mode
- Context manager `get_db()` with auto-commit/rollback
- All CRUD centralized, strategy scripts have zero direct SQL
- `get_prices_as_dataframe()` returns pandas DataFrame
- Phase 5 additions:
  - `get_watchlist_item(symbol)` — Get single entry (incl. disabled)
  - `set_ticker_enabled(symbol, enabled)` — Soft delete/restore
  - `get_price_count(symbol)` — Check if re-fetch needed on restore
  - `get_latest_price_date(symbol)` — For incremental fetching

### `lib/config.py` — Config Loading & Watchlist Sync
- Reads from `config/tickers.json`
- `sync_watchlist()` idempotent sync to DB
- `get_monitored_tickers()` / `get_yfinance_tickers()` by group

### `lib/indicators.py` — Shared Technical Indicator Library

| Indicator | Function |
|-----------|----------|
| SMA / EMA | `sma()`, `ema()` |
| RSI (Wilder) | `rsi()` |
| MACD | `macd()` → (line, signal, histogram) |
| ATR | `atr()` |
| Bollinger Bandwidth | `bollinger_bandwidth()`, `bbw_percentile()` |
| Consecutive streak | `consecutive_streak()` |
| RSI divergence | `detect_rsi_divergence()` |
| MACD divergence | `detect_macd_divergence()` |
| Candlestick | `detect_hammer()` (hammer/doji) |
| Price change | `pct_change()`, `pct_from_value()` |
| Weekly resample | `resample_weekly()` |
| Elder Impulse | `elder_impulse_weekly()` |
| Timezone | `normalize_tz()` |

### `lib/models.py` — Data Models
Python `dataclass` with `to_db_dict()` and `from_db_row()`:

- `TickerInfo` — Watchlist stock info
- `StrategyResult` — Base class
- `Stage2Result` / `VCPResult` / `BottomFisherResult` / `BuyingChecklistResult` — Strategy-specific
- `MarketPulseResult` — Market macro state
- `SignalChange` — Signal change event

### `lib/report.py` — Report Generation
- Jinja2 environment, loads `templates/*.j2`
- Custom filters: `tg_escape`, `score_emoji_*`, `chg_emoji`, `score_bar`, `progress_bar`, `fmt_pct`, `fmt_price`, `fmt_val`
- `split_telegram_message()` — Split at paragraph boundaries (Telegram 4000 char limit)
- `save_reports()` — Unified MD + Telegram HTML + manifest save

### `lib/pipeline.py` — Web Ticker Pipeline + Bulk Refresh (Phase 5)

#### `validate_ticker(symbol)` — Three-Layer Validation

| Layer | Method | Latency | Description |
|-------|--------|---------|-------------|
| L1 | Regex format | ~0ms | 1-5 uppercase, optional `.A`/`.B` |
| L2 | `yf.Ticker.info` metadata | ~1s | Confirm name exists |
| L3 | Trial 5-day fetch | ~1s | Confirm data source works |

#### `run_single_ticker_pipeline(symbol, name, sector)` — Full Pipeline

| Step | Operation | Description |
|------|-----------|-------------|
| 1 | Fetch 365D prices (yfinance) → `upsert_prices()` | Price data to DB |
| 2 | Stage 2 analysis → `save_strategy_result()` + `upsert_strategy_state()` | Trend confirmation |
| 3 | VCP analysis (only if Stage 2 active) | Right-side breakout |
| 4 | Bottom Fisher analysis | Left-side reversal |
| 5 | Buying Checklist analysis | Comprehensive buy confirmation |

**Note**: Pipeline uses today's date as `date_str`. The web layer uses a **fallback query** when dates mismatch — falls back to the ticker's most recent result.

#### `refresh_all_prices()` — Bulk Refresh + Auto Market Pulse

Triggered by "Refresh Prices" button. After refresh, auto-calls `_update_market_pulse()` ensuring date consistency.

---

## Jinja2 Report Templates (templates/)

| Template | Purpose |
|----------|---------|
| `stage2_md.j2` / `stage2_tg.j2` | Stage 2 report (MD / Telegram) |
| `vcp_md.j2` / `vcp_tg.j2` | VCP report (MD / Telegram) |
| `bottom_md.j2` / `bottom_tg.j2` | Bottom-fishing report (MD / Telegram) |
| `pulse_md.j2` / `pulse_tg.j2` | Market Pulse report (MD / Telegram) |

---

## Usage

### First-Time Setup

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Initialize database
python -m lib.db init

# 3. Sync watchlist
python lib/config.py

# 4. Migrate from old project (optional)
python scripts/migrate_prices.py --source D:/eh/projects/workspace/stocks
```

### Daily Execution

```bash
# One-click (recommended) — auto: price fetch → strategies → Market Pulse
python scripts/save_prices_yfinance.py

# Or step-by-step (for debugging)
python scripts/market_pulse.py             # Market thermometer
python scripts/stage2_monitor.py           # Stage 2
python scripts/vcp_scanner.py              # VCP
python scripts/bottom_fisher.py            # Bottom-fishing
python scripts/buying_checklist.py         # Buying checklist

# Silent mode (cron behavior, suppress stdout)
python scripts/market_pulse.py --cron
python scripts/stage2_monitor.py --cron
python scripts/vcp_scanner.py --cron
python scripts/bottom_fisher.py --cron
python scripts/buying_checklist.py --cron
```

### CLI Arguments

| Script | Argument | Description |
|--------|----------|-------------|
| `save_prices_yfinance.py` | `--mode all\|yfinance_only` | Fetch scope (default: all) |
| `save_prices_yfinance.py` | `--test TICKER` | Test single ticker |
| `save_prices_yfinance.py` | `--no-csv` | Skip CSV backup |
| `market_pulse.py` | `--cron` | Suppress stdout |
| `stage2_monitor.py` | `--cron` | Suppress stdout |
| `vcp_scanner.py` | `--cron` | Suppress stdout |
| `bottom_fisher.py` | `--cron` | Suppress stdout |
| `buying_checklist.py` | `--cron` | Suppress stdout |

### Database Tools

```bash
python -m lib.db init    # Initialize (idempotent)
python -m lib.db stats   # View statistics
```

---

## Directory Structure

```
stock-tracker/
├── config/
│   └── tickers.json              # Monitored stocks list
├── data/
│   ├── stock_tracker.db          # SQLite database (.gitignore)
│   └── prices/                   # CSV backup cache (.gitignore)
├── lib/
│   ├── __init__.py
│   ├── config.py                 # Config loading & watchlist sync
│   ├── db.py                     # SQLite DAL (~800 lines, project core)
│   ├── indicators.py             # Shared technical indicators (incl. Elder Impulse)
│   ├── models.py                 # Data models (dataclass)
│   ├── pipeline.py               # Web pipeline + bulk refresh + auto Market Pulse
│   ├── report.py                 # Report generation (Jinja2)
│   └── technical_analysis.py     # 4 technical analysis systems (MA/momentum/S&R/Fibonacci)
├── templates/
│   ├── stage2_md.j2 / stage2_tg.j2
│   ├── vcp_md.j2 / vcp_tg.j2
│   ├── bottom_md.j2 / bottom_tg.j2
│   └── pulse_md.j2 / pulse_tg.j2
├── scripts/
│   ├── save_prices.py            # ⚠️ Deprecated (Stooq unavailable)
│   ├── save_prices_yfinance.py   # Data collection v2.1 (incremental + auto-chain)
│   ├── market_pulse.py           # Strategy 0: Market Thermometer v4.0 (incl. Distribution Day analysis)
│   ├── stage2_monitor.py         # Strategy 1: Stage 2 v4.0
│   ├── vcp_scanner.py            # Strategy 2: VCP v2.0
│   ├── bottom_fisher.py          # Strategy 3: Bottom Fisher v2.0
│   ├── buying_checklist.py       # Strategy 4: Buying Checklist v1.0
│   └── migrate_prices.py         # Data migration (CSV/JSON → SQLite)
├── reports/
│   └── daily/                    # Daily report archive (.md + .html + manifest)
├── web/                          # Phase 4-6: Web Dashboard
│   ├── app.py                    # FastAPI entry point
│   ├── deps.py                   # Jinja2 templates + filters + i18n injection
│   ├── routes/                   # Routes (dashboard/watchlist/ticker/api)
│   ├── templates/                # HTML templates (base/dashboard/watchlist/detail)
│   ├── static/                   # CSS (dark theme) + JS (sort/filter + i18n)
│   └── i18n/                     # Internationalization module
│       ├── __init__.py
│       ├── core.py               # i18n engine (load/lookup/detect/translator factory)
│       └── locales/
│           ├── en.json           # English language pack
│           └── zh.json           # Chinese language pack
├── logs/                         # Log files (.gitignore)
├── requirements.txt              # Python dependencies
├── Dockerfile                    # Multi-stage Docker build
├── docker-compose.yml            # Docker Compose deployment
├── DEPLOY.md                     # Deployment guide
├── .gitignore
├── README.md                     # Chinese version
└── README_EN.md                  # This document (English)
```

---

## Pipeline Execution Order

```bash
# Option 1: One-click (recommended, v2.1 auto-chain)
python scripts/save_prices_yfinance.py
# Auto: incremental price fetch → strategy calculation → Market Pulse update

# Option 2: Step-by-step (for debugging)
Step 1:  python scripts/save_prices_yfinance.py  # yfinance (incremental)
Step 2:  python scripts/market_pulse.py --cron    # Market thermometer
Step 3:  python scripts/stage2_monitor.py --cron  # Stage 2
Step 4:  python scripts/vcp_scanner.py --cron     # VCP
Step 5:  python scripts/bottom_fisher.py --cron   # Bottom-fishing
Step 6:  python scripts/buying_checklist.py --cron # Buying checklist
```

- **Option 1**: `save_prices_yfinance.py` v2.1 auto-runs strategies + Market Pulse after price fetch
- **Option 2**: Step 1 failure doesn't affect later steps (Market Pulse degrades gracefully)
- Step 2 (Market Pulse) pushed first — big picture before individual stocks
- Step 4 (VCP) depends on Step 3 (Stage 2)
- Step 5 (Bottom Fisher) runs independently
- Step 6 (Buying Checklist) runs independently, uses multi-strategy states for confirmation
- Each step's failure doesn't block later steps (except VCP depends on Stage 2)

### Web Bulk Refresh Data Flow

```
Web "Refresh Prices" button (refresh_all_prices):
  watchlist → yfinance → stock_prices ✅
                       → strategy_results (date=today) ✅
                       → strategy_states ✅
                       → market_pulse (date=today) ✅  ← auto-chained

Script save_prices_yfinance.py (v2.1):
  yfinance → stock_prices (incremental) ✅
           → strategy_results (date=today) ✅  ← auto-chained
           → strategy_states ✅              ← auto-chained
           → market_pulse (date=today) ✅      ← auto-chained

Page rendering:
  market_pulse (read) → latest_date = today
  strategy_results WHERE date=today (read) → ✅ dates match!
  (fallback to latest record if mismatch)
```

---

## Parameter Tuning Guide

All strategy parameters are centralized in `*_PARAMS` dicts at the top of each Python script. Changes take effect immediately.

### VCP Scanner Key Parameters

```python
VCP_PARAMS = {
    "bbw_percentile_threshold": 25,   # ↓ stricter (e.g. 15), ↑ looser (e.g. 35)
    "vol_ratio_threshold": 0.75,      # ↓ require more extreme low volume
    "strong_signal_min": 4,           # ↑ fewer signals, ↓ more signals
}
```

### Bottom Fisher Key Parameters

```python
BF_PARAMS = {
    "min_drawdown_from_52w_high": -15,  # ↑ less decline needed, ↓ deeper drop required
    "rsi_oversold": 35,                 # ↑ looser, ↓ extreme oversold only
    "vol_ratio_threshold": 0.6,         # ↑ looser, ↓ more extreme low volume
    "support_proximity_pct": 3.0,       # ↑ wider support zone
    "strong_signal_min": 5,             # ↑ fewer signals, ↓ more signals
}
```

### Buying Checklist Key Parameters

```python
BC_PARAMS = {
    "elder_impulse_required": "green",    # Weekly Elder Impulse color requirement
    "rsi_healthy_low": 50,                # ↓ lower RSI floor
    "rsi_healthy_high": 70,               # ↑ RSI ceiling, avoid overbought
    "macd_positive_required": True,       # MACD positive confirmation
    "max_drawdown_from_52w": -25,         # ↑ allow larger drawdown
    "strong_signal_min": 6,               # ↑ fewer signals, ↓ more signals
}
```

---

## Internationalization (i18n) — Phase 6

### Overview

Web Dashboard fully supports English/Chinese bilingual switching. Default language is English; users can switch to Chinese via the language button in the navigation bar.

### Language Detection Priority

| Priority | Source | Description |
|----------|--------|-------------|
| 1 | `?lang=xx` query parameter | Explicit URL specification |
| 2 | `lang` cookie | Browser-remembered preference |
| 3 | `Accept-Language` header | Browser default language |
| 4 | Default `en` | Fallback to English |

### Coverage

| Layer | Scope | Implementation |
|-------|-------|---------------|
| HTML templates | 4 page templates (base/dashboard/watchlist/ticker_detail) | Jinja2 `_t()` function |
| JavaScript | All user-visible text in main.js | `window.I18N` pack + `_t()` |
| API responses | All messages in api.py (success/error/info) | `get_translator()` factory |
| Backend filters | regime_label / change_type mappings in deps.py | i18n context injection |
| Notification templates | 8 `.j2` templates (Markdown + Telegram) | Direct English |

### Language Pack Structure

Located at `web/i18n/locales/`, JSON format with dot-separated nested keys:

```json
{
  "nav": {
    "dashboard": "Dashboard",
    "watchlist": "Watchlist"
  },
  "dashboard": {
    "title": "Market Overview",
    "market_pulse": "Market Pulse"
  }
}
```

Lookup supports fallback chain: `requested language → English → raw key`. Supports `{placeholder}` interpolation.

---

## Dependencies

| Dependency | Version | Purpose |
|-----------|---------|---------|
| `pandas` | ≥ 2.0.0 | Core data processing |
| `numpy` | ≥ 1.24.0 | Numerical computation |
| `yfinance` | ≥ 0.2.30 | Yahoo Finance data source |
| `pandas-datareader` | ≥ 0.10.0 | Auxiliary data fetching |
| `jinja2` | ≥ 3.1.0 | Template engine |
| *SQLite* | *built-in* | Database (Python stdlib) |
| `fastapi` | ≥ 0.100.0 | Web framework |
| `uvicorn` | ≥ 0.23.0 | ASGI server |

---

## Web Dashboard (Phase 4-6)

### Overview

Local Web Dashboard built with FastAPI + Jinja2 SSR + Chart.js, providing three core pages. Reuses all `lib/db.py` query APIs from Phase 1-3, zero DB modifications. Phase 6 additions: i18n support (EN/ZH) + technical analysis 4-tab panel + 4-strategy status cards.

### Getting Started

```bash
# Option 1: Direct start
python -m web.app

# Option 2: uvicorn with hot-reload
uvicorn web.app:app --reload --port 8000

# Open browser
# http://127.0.0.1:8000
```

> 📖 **Full deployment guide** (Linux server / Oracle Cloud / domain / HTTPS) — see [DEPLOY.md](DEPLOY.md)

### Three Core Pages

| Page | Path | Features |
|------|------|----------|
| **Dashboard** | `/` | Market Pulse status + Distribution Days indicator bar + 4-strategy signal summary (Stage 2 / VCP / Bottom Fisher / Buying Checklist) + recent signal changes + 30-day trend chart |
| **Watchlist** | `/watchlist` | Multi-strategy comparison table (4 strategy status/scores), sector filter / search / signal-only filter + **Ticker add/remove** |
| **Ticker Detail** | `/ticker/{symbol}` | 4-strategy status cards + 4-tab technical analysis (MA / Momentum / S&R / Fibonacci) + condition details + key metrics + signal history + score trend chart |

### Web Ticker Management (Phase 5)

Add tickers via the **"➕ Add Ticker"** button and remove via **"×"** on each row in the Watchlist page. No need to edit `tickers.json`.

#### Add Flow

```
User enters ticker → "Validate" → yfinance 3-layer validation → Show metadata (name/sector/price)
                                                                    ↓
                              "Add to Watchlist" → Write to watchlist table
                                                                    ↓
                              run_single_ticker_pipeline() → Fetch prices + run all strategies
                                                                    ↓
                                                             Auto-refresh page → Show complete data
```

**Special cases**:
- **Already exists and enabled** → Prompt already in list, block duplicate
- **Previously removed (enabled=0)** → Prompt to restore, reuse existing data or re-fetch
- **Brand new ticker** → Full validation + pipeline execution

#### Deletion

**Soft delete** (`enabled=0`), no physical data deletion. Can be restored via "Add" later.

### API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/tickers/check/{symbol}` | Validate ticker (3-layer + existence check) |
| `POST /api/tickers` | Add ticker (validate → write → run pipeline) |
| `DELETE /api/tickers/{symbol}` | Soft-delete ticker (set `enabled=0`) |
| `GET /api/dashboard` | Dashboard full data JSON |
| `GET /api/market-pulse/latest` | Latest Market Pulse |
| `GET /api/market-pulse/history?days=30` | Market Pulse history |
| `GET /api/signals/recent?limit=20` | Recent signal changes |
| `GET /api/ticker/{symbol}` | Individual stock strategy data |
| `GET /api/ticker/{symbol}/history?strategy=stage2&days=30` | Strategy history per ticker |
| `POST /api/prices/refresh` | Bulk price refresh (SSE streaming progress) |

### Tech Stack

| Component | Choice | Description |
|-----------|--------|-------------|
| Backend | FastAPI + Uvicorn | High-performance ASGI framework |
| Templates | Jinja2 SSR | Server-side rendering, reuses Phase 3 |
| Styling | Hand-crafted CSS (dark theme) | Finance tool standard, easy on eyes |
| Charts | Chart.js (CDN) | Lightweight line charts |
| Interaction | Vanilla JS | Table sort/filter + Ticker management (Modal + Fetch API) |
| i18n | JSON language packs + i18n engine | EN/ZH bilingual, cookie persistence, fallback chain |
| Pipeline | lib/pipeline.py | Ticker validation + fetch + strategy analysis + auto Market Pulse |

### Web Directory Structure

```
web/
├── __init__.py
├── app.py                    # FastAPI entry point
├── deps.py                   # Jinja2 engine + custom filters + i18n context injection
├── routes/
│   ├── __init__.py
│   ├── dashboard.py          # Dashboard route (with fallback query)
│   ├── watchlist.py          # Watchlist route (with fallback query)
│   ├── ticker.py             # Ticker Detail route (with technical analysis + fallback)
│   └── api.py                # JSON API (Ticker CRUD + SSE refresh + fallback)
├── templates/
│   ├── base.html             # Base layout (nav + language switch + footer + modal overlay)
│   ├── dashboard.html        # Dashboard (4-strategy signal summary)
│   ├── watchlist.html        # Watchlist (add ticker modal + remove button)
│   └── ticker_detail.html    # Ticker Detail (4 strategy cards + 4-tab technical analysis)
├── static/
│   ├── css/style.css         # Dark theme (modal + validation + tab panel styles)
│   └── js/main.js            # Table sort/filter + ticker management + i18n translation
└── i18n/
    ├── __init__.py
    ├── core.py               # i18n engine (pack loading / translation lookup / language detection / translator factory)
    └── locales/
        ├── en.json           # English language pack (~220 translation keys)
        └── zh.json           # Chinese language pack (~220 translation keys)
```
