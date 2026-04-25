#!/usr/bin/env python3
"""
Scheduler — runs the pipeline daily at the configured time.

Two deployment options:

OPTION 1: Run this script (keeps running in background)
  python scheduler.py
  # or with nohup:
  nohup python scheduler.py > scheduler.log 2>&1 &

OPTION 2: Use system cron (recommended for servers)
  # Edit crontab:
  crontab -e

  # Add this line (runs at 10:00 AM IST = 4:30 AM UTC):
  30 4 * * * cd /path/to/assured-referral-autoposter && /usr/bin/python3 main.py >> output/cron.log 2>&1

OPTION 3: Use systemd timer (Linux servers)
  See the systemd/ folder for service and timer files.

OPTION 4: Use GitHub Actions (free, no server needed)
  See .github/workflows/daily-post.yml
"""

import time
import schedule
from datetime import datetime
from config.settings import Config
from main import run_pipeline


def job():
    """The daily posting job."""
    print(f"\n{'=' * 60}")
    print(f"⏰ Scheduled job started at {datetime.now().isoformat()}")
    print(f"{'=' * 60}")

    try:
        results = run_pipeline(num_slides=5, dry_run=False, use_ai_images=True)
        print(f"\n✅ Pipeline completed at {datetime.now().isoformat()}")
    except Exception as e:
        print(f"\n❌ Pipeline failed: {e}")


def main():
    posting_time = Config.POSTING_TIME  # e.g., "10:00"

    print(f"🕐 Scheduler started. Will run daily at {posting_time} IST")
    print(f"   Current time: {datetime.now().strftime('%H:%M:%S')}")
    print(f"   Press Ctrl+C to stop\n")

    # Schedule the daily job
    schedule.every().day.at(posting_time).do(job)

    # Keep running
    while True:
        schedule.run_pending()
        time.sleep(60)  # Check every minute


if __name__ == "__main__":
    main()
