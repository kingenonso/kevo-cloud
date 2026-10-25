#!/bin/bash
# Fixed 2026-10-25: this used to `cd ~/KEVO`, which under WSL resolves to
# the old WSL-homed clone (~/KEVO = /home/king/KEVO), not the native
# Windows clone (C:\Users\kingn\KEVO) that's been the single source of
# truth since 2026-10-22. That mismatch meant autosave had been silently
# running against an abandoned, increasingly stale clone - it almost
# certainly logged "no changes, skipped" run after run while real work
# piled up, untracked, in the Windows clone instead.
REPO_DIR="/mnt/c/Users/kingn/KEVO"
cd "$REPO_DIR" || exit 1
if [ -n "$(git status --porcelain)" ]; then
  git add -A
  git commit -m "Autosave $(date '+%Y-%m-%d %H:%M:%S')"
  git push origin main >> "$REPO_DIR/autosave.log" 2>&1
  echo "$(date '+%Y-%m-%d %H:%M:%S'): committed and pushed" >> "$REPO_DIR/autosave.log"
else
  echo "$(date '+%Y-%m-%d %H:%M:%S'): no changes, skipped" >> "$REPO_DIR/autosave.log"
fi
