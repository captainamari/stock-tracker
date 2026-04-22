#!/bin/bash
# Stock Tracker — Daily Pipeline (Cron Entry)
# Run the three-phase pipeline: data ingestion → strategy compute → Telegram push
#
# Recommended crontab (US Eastern, after market close):
#   30 16 * * 1-5 /path/to/scripts/daily_pipeline.sh
#
# Or for Docker:
#   30 16 * * 1-5 cd /path/to/stock-tracker && docker compose exec -T web python scripts/daily_pipeline.py
#
# Usage:
#   bash scripts/daily_pipeline.sh                     # Full pipeline
#   bash scripts/daily_pipeline.sh --notify-only       # Only push notifications
#   bash scripts/daily_pipeline.sh --dry-run           # Test without sending

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

# Load .env if exists
if [ -f ".env" ]; then
    set -a
    source .env
    set +a
fi

# Detect execution mode
MODE=""
case "${1:-}" in
    --docker) MODE="docker"; shift ;;
    --venv)   MODE="venv"; shift ;;
    *)
        if command -v docker &>/dev/null && sudo docker compose ps --status running 2>/dev/null | grep -q "stock-tracker"; then
            MODE="docker"
        elif [ -f "venv/bin/activate" ] || [ -f ".venv/bin/activate" ]; then
            MODE="venv"
        else
            echo "❌ No runtime environment detected"
            exit 1
        fi
        ;;
esac

if [ "$MODE" = "docker" ]; then
    exec sudo docker compose exec -T web python scripts/daily_pipeline.py "$@"
else
    if [ -f "venv/bin/activate" ]; then
        source venv/bin/activate
    elif [ -f ".venv/bin/activate" ]; then
        source .venv/bin/activate
    fi
    exec python3 scripts/daily_pipeline.py "$@"
fi
