#!/bin/bash
cd ~/KEVO || exit 1
if [ -n "$(git status --porcelain)" ]; then
  git add -A
  git commit -m "Autosave $(date '+%Y-%m-%d %H:%M:%S')"
  git push origin main >> ~/KEVO/autosave.log 2>&1
  echo "$(date '+%Y-%m-%d %H:%M:%S'): committed and pushed" >> ~/KEVO/autosave.log
else
  echo "$(date '+%Y-%m-%d %H:%M:%S'): no changes, skipped" >> ~/KEVO/autosave.log
fi
