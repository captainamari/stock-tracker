#!/usr/bin/env bash
set -euo pipefail
printf "%s\n" "Retired legacy automation. Disable old cron entries and follow DEPLOY.md for the unified scheduler, workers and safe migration." >&2
exit 2
