# Stock Tracker — Trading Intelligence Platform

A quantitative trading intelligence platform for US stock analysis, featuring multi-strategy signal generation, real-time momentum tracking, and a modular web dashboard.

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────────┐
│  Frontend (React SPA)                          /app              │
│  React 18 + TypeScript + TailwindCSS + Zustand                   │
│  Draggable widget grid (react-grid-layout)                       │
│  WebSocket real-time updates                                     │
└─────────────────────────┬────────────────────────────────────────┘
                          │ REST API + WebSocket
┌─────────────────────────┴────────────────────────────────────────┐
│  Backend (FastAPI)                                                │
│  ┌────────────────┐  ┌──────────────────┐  ┌─────────────────┐  │
│  │ API v1 Layer   │  │ Strategy Engine   │  │ Data Layer      │  │
│  │ 18 endpoints   │  │ Plugin Registry   │  │ SQLite + WAL    │  │
│  │ + WebSocket    │  │ 8 strategies      │  │ Repository      │  │
│  └────────────────┘  └──────────────────┘  └─────────────────┘  │
│                              │                                    │
│  ┌───────────────────────────┴───────────────────────────────┐   │
│  │  Strategy Registry (auto-discover, register, dispatch)     │   │
│  │  • Market Pulse        • Stage 2 Monitor                   │   │
│  │  • VCP Scanner         • Bottom Fisher                     │   │
│  │  • Buying Checklist    • Momentum V3 (NEW)                 │   │
│  │  • Sector Momentum     • Market Sentiment                  │   │
│  └───────────────────────────────────────────────────────────┘   │
└─────────────────────────┬────────────────────────────────────────┘
                          │
┌─────────────────────────┴────────────────────────────────────────┐
│  Data Pipeline                                                    │
│  daily_pipeline.py → prices → market_pulse → momentum_v3         │
│                    → stage2 → vcp → bottom_fisher → checklist     │
│                    → Telegram notification                        │
└──────────────────────────────────────────────────────────────────┘
```

## Quick Start

### Prerequisites

- Python 3.10+
- Node.js 18+ (for frontend development only)

### Backend

```bash
# Install Python dependencies
pip install -r requirements.txt

# Initialize database
python -m lib.db init

# Run database migration (adds momentum tables)
python -m lib.db migrate

# Fetch initial price data
python scripts/save_prices_yfinance.py --mode all

# Run all strategies
python scripts/daily_pipeline.py

# Start web server
python -m web.app
```

Server runs at `http://localhost:8000`

### Frontend (Development)

```bash
cd frontend
npm install
npm run dev    # Vite dev server at :3000, proxies /api to :8000
```

### Access Points

| URL | Description |
|-----|-------------|
| `http://localhost:8000/app` | New React SPA (IBKR-style) |
| `http://localhost:8000/` | Legacy SSR dashboard |
| `http://localhost:8000/docs` | API documentation (Swagger) |

---

## Project Structure

```
stock-tracker/
├── frontend/                    # React SPA (Vite + TypeScript)
│   ├── src/
│   │   ├── api/                 # REST + WebSocket clients
│   │   ├── components/
│   │   │   ├── layout/          # Header, GridDashboard, WidgetPanel
│   │   │   └── widgets/         # MarketPulse, Heatmap, SignalFeed, etc.
│   │   ├── stores/              # Zustand (appStore, layoutStore)
│   │   └── types/               # TypeScript type definitions
│   └── package.json
│
├── lib/                         # Shared Python library
│   ├── db.py                    # SQLite DAL (all data access)
│   ├── indicators.py            # Technical indicator calculations
│   ├── technical_analysis.py    # Real-time TA for ticker detail
│   ├── strategy/                # Strategy Plugin System
│   │   ├── base.py              # BaseStrategy abstract class
│   │   ├── registry.py          # StrategyRegistry (discover/run)
│   │   ├── loader.py            # Load all strategies
│   │   ├── adapters.py          # Legacy strategy wrappers
│   │   └── momentum_v3/         # Momentum V3 (new)
│   │       ├── core.py          # Composite Momentum Score V2
│   │       ├── signals.py       # V3 Signal Engine
│   │       ├── strategy.py      # 3 strategy classes
│   │       └── runner.py        # Pipeline runner
│   └── migrations/              # Database migrations
│
├── scripts/                     # Strategy scripts + pipeline
│   ├── daily_pipeline.py        # Three-phase daily automation
│   ├── save_prices_yfinance.py  # Data ingestion
│   ├── market_pulse.py          # Market Pulse strategy
│   ├── stage2_monitor.py        # Stage 2 strategy
│   ├── vcp_scanner.py           # VCP strategy
│   ├── bottom_fisher.py         # Bottom Fisher strategy
│   └── buying_checklist.py      # Buying Checklist strategy
│
├── web/                         # FastAPI web layer
│   ├── app.py                   # Main entry (mounts all routes)
│   ├── routes/
│   │   ├── v1/                  # API v1 (new)
│   │   │   ├── strategies.py    # Strategy CRUD + run
│   │   │   ├── momentum.py      # Momentum scores/heatmap/history
│   │   │   ├── market.py        # Market overview/pulse/sectors
│   │   │   ├── signals.py       # Signal feed/active/recent
│   │   │   └── websocket.py     # WebSocket real-time
│   │   ├── api.py               # Legacy API (preserved)
│   │   ├── dashboard.py         # Legacy SSR page
│   │   ├── watchlist.py         # Legacy SSR page
│   │   └── ticker.py            # Legacy SSR page
│   └── static/app/              # Built SPA output
│
├── config/tickers.json          # Monitored tickers + sector ETFs
├── data/stock_tracker.db        # SQLite database
├── docker-compose.yml           # Docker deployment
├── Dockerfile                   # Multi-stage build
└── requirements.txt             # Python dependencies
```

---

## Strategies

| Strategy | Layer | Description |
|----------|-------|-------------|
| **Market Pulse** | Market | IBD Distribution Day + multi-dimensional market thermometer |
| **Market Sentiment** | Market | SPY/QQQ momentum → Risk-on/Risk-off |
| **Sector Momentum** | Sector | ETF momentum for hardware/software/biotech sectors |
| **Momentum V3** | Stock | Three-layer composite momentum with V3 entry/exit rules |
| **Stage 2 Monitor** | Stock | Weinstein Stage Analysis + Minervini Trend Template |
| **VCP Scanner** | Stock | Volatility Contraction Pattern detection |
| **Bottom Fisher** | Stock | Mean-reversion oversold + reversal confirmation |
| **Buying Checklist** | Stock | Elder Impulse + multi-factor buy confirmation |

### Adding a New Strategy

```python
# lib/strategy/my_strategy.py
from lib.strategy.base import BaseStrategy, StrategyResult, StrategyLayer

class MyStrategy(BaseStrategy):
    name = "my_strategy"
    display_name = "My Strategy"
    version = "1.0.0"
    layer = StrategyLayer.STOCK
    min_data_points = 50

    def compute(self, symbol, prices_df, context=None):
        # Your logic here
        return StrategyResult(symbol=symbol, date="...", strategy=self.name, ...)

# Register in lib/strategy/loader.py:
from lib.strategy.my_strategy import MyStrategy
registry.register(MyStrategy)
```

---

## API v1 Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/strategies/` | List all 8 strategies |
| GET | `/api/v1/strategies/{name}` | Strategy detail + config schema |
| POST | `/api/v1/strategies/{name}/run` | Run strategy on symbols |
| POST | `/api/v1/strategies/run-all` | Batch run all strategies |
| GET | `/api/v1/momentum/scores` | Latest momentum scores |
| GET | `/api/v1/momentum/heatmap` | Three-layer heatmap data |
| GET | `/api/v1/momentum/history/{symbol}` | Score history (charting) |
| GET | `/api/v1/momentum/relative` | Relative strength matrix |
| POST | `/api/v1/momentum/refresh` | Trigger momentum pipeline |
| GET | `/api/v1/market/overview` | Combined market overview |
| GET | `/api/v1/market/pulse` | Latest Market Pulse |
| GET | `/api/v1/market/pulse/history` | Pulse history |
| GET | `/api/v1/market/sectors` | Sector definitions + scores |
| GET | `/api/v1/signals/feed` | Signal feed (sorted by urgency) |
| GET | `/api/v1/signals/recent` | Recent signal changes |
| GET | `/api/v1/signals/active` | Currently active signals |
| WS | `/api/v1/ws` | WebSocket (signals/scores/refresh) |
| GET | `/api/v1/ws/status` | Connection status |

---

## Deployment

See [DEPLOY_V2.md](./DEPLOY_V2.md) for full deployment guide including:
- Docker deployment (recommended)
- Database migration from v1
- Cron job setup for daily pipeline
- Nginx + HTTPS configuration

---

## Frontend Widget System

The React SPA features a modular, draggable widget dashboard:

| Widget | Function |
|--------|----------|
| **Market Pulse** | Market regime gauge + SPY/QQQ scores + price |
| **Momentum Heatmap** | Three-layer color-coded score grid |
| **Signal Feed** | Real-time signals sorted by urgency |
| **Position Summary** | All stocks: score/regime/action table |
| **Score Chart** | Canvas-rendered score trend line |

**Layout Features:**
- Drag widgets by header to reposition
- Resize from bottom-right corner
- Toggle widget visibility via settings panel (⚙)
- 3 presets: Full Dashboard / Momentum Focus / Signals Only
- Layout persists in localStorage

---

## Database Schema

| Table | Purpose |
|-------|---------|
| `watchlist` | Monitored tickers (soft-delete) |
| `stock_prices` | Daily OHLCV |
| `strategy_results` | All strategy daily outputs (JSON metrics) |
| `strategy_states` | Current signal state per ticker |
| `signal_changes` | Entry/exit history |
| `market_pulse` | Market regime data |
| `momentum_scores` | Momentum V3 scores (3 layers) |
| `sector_mappings` | Stock → sector relationships |
| `sector_definitions` | Sector ETF configuration |
| `score_history` | Compact score storage for charts |
| `pipeline_runs` | Idempotent pipeline execution log |
| `notification_log` | Telegram push deduplication |

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI + Uvicorn |
| Frontend | React 18 + TypeScript + Vite |
| Styling | TailwindCSS (dark financial theme) |
| State | Zustand (persist middleware) |
| Layout | react-grid-layout |
| Charts | Canvas API (custom) |
| Database | SQLite (WAL mode) |
| Data Source | yfinance |
| Real-time | WebSocket |
| Notifications | Telegram Bot API |
| Deployment | Docker + docker-compose |

---

## License

Private project. All rights reserved.
