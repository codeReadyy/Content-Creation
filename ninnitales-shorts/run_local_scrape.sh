#!/usr/bin/env bash
# run_local_scrape.sh — LOCAL daily job: scrape + build Shorts, push them for the cloud.
#
# Runs on the Mac (residential IP) where YouTube scraping works. Pulls latest, stages
# N scraped Shorts into pending/, and pushes. The cloud daily workflow then publishes
# them. Scheduled via com.ninnitales.scrape.plist (launchd).
#
# Usage: run_local_scrape.sh [count]   (default 2)
set -euo pipefail

# launchd runs with a minimal PATH — add Homebrew (ffmpeg/yt-dlp) + Python.
export PATH="/opt/homebrew/bin:/usr/local/bin:/Library/Frameworks/Python.framework/Versions/3.13/bin:/usr/bin:/bin:/usr/sbin:/sbin"

REPO="$(cd "$(dirname "$0")/.." && pwd)"   # ninnitales-shorts/.. = repo root
cd "$REPO"

echo "=== $(date) — local scrape stage ==="
git pull --rebase --autostash origin main || true

( cd ninnitales-shorts && python3 scrape_stage.py --count "${1:-2}" ) || {
  echo "scrape_stage failed — nothing staged this run."; exit 0; }

git add ninnitales-shorts/pending/
if ! git diff --cached --quiet; then
  git commit -m "chore(ninnitales): stage scraped Shorts [skip ci]"
  git pull --rebase --autostash origin main || true
  git push
  echo "pushed staged Shorts."
else
  echo "nothing new to stage."
fi
