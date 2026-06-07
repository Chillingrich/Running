#!/bin/bash
# sync_running.command
# ดับเบิ้ลคลิกไฟล์นี้เพื่อ sync running sessions

cd "$(dirname "$0")"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  🏃 Running Sync"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Run Python script
python3 "$(dirname "$0")/sync_running.py"

# Open dashboard after sync
open -a "Google Chrome" https://chillingrich.github.io/Running/dashboard.html
