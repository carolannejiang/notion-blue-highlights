#!/bin/sh
# Install the launchd job for this checkout (macOS). Re-run after moving the repo.
set -e
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
LABEL=com.notion-highlight-collector
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

mkdir -p "$HOME/Library/LaunchAgents"
sed "s#__REPO_DIR__#$REPO_DIR#g" "$REPO_DIR/$LABEL.plist" > "$PLIST"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "installed $LABEL -> $REPO_DIR/sync.py (log: $REPO_DIR/sync.log)"
