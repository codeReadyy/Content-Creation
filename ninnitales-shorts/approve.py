"""approve.py — review-and-publish a queued NinniTales Short.

The manual half of the workflow: `run_pipeline.py --stitch-only` builds Shorts into
queue/ (each with a sidecar .json holding its title); you eyeball the mp4, then run
this to publish the one you approve. Loads .env automatically, uploads to the
NinniTales channel, and moves the published clip into posted/ so it isn't offered again.

Usage:
    python approve.py                      # list the queue and pick interactively
    python approve.py queue/short_X.mp4    # publish a specific file
    python approve.py queue/short_X.mp4 --title "Custom title"
    python approve.py queue/short_X.mp4 --publish-at 2026-06-20T14:00:00Z  # schedule
    python approve.py ... --keep           # don't move to posted/ after upload
"""

import argparse
import json
from pathlib import Path

import run_pipeline
import upload_youtube
from analytics import ledger

HERE = Path(__file__).parent
QUEUE = HERE / "queue"
POSTED = HERE / "posted"


def _meta(mp4: Path) -> tuple[str | None, str, list[str], str]:
    """Return (title, description, tags, theme) from the sidecar, with fallbacks."""
    sidecar = mp4.with_suffix(".json")
    if sidecar.exists():
        d = json.loads(sidecar.read_text())
        return (d.get("title"),
                d.get("description", run_pipeline.DESCRIPTION),
                d.get("tags", run_pipeline.TAGS),
                d.get("theme", "untagged"))
    return None, run_pipeline.DESCRIPTION, run_pipeline.TAGS, "untagged"


def _list() -> list[Path]:
    vids = sorted(QUEUE.glob("short_*.mp4"))
    if not vids:
        print("queue is empty — build one with:\n"
              "  python run_pipeline.py --count 1 --source generated --stitch-only")
        return vids
    print("Queued Shorts:")
    for i, v in enumerate(vids, 1):
        title, _d, _t, theme = _meta(v)
        print(f"  [{i}] {v.name}  —  {title or '(no title; pass --title)'}  [{theme}]")
    return vids


def main() -> None:
    ap = argparse.ArgumentParser(description="Publish a queued Short to NinniTales.")
    ap.add_argument("video", nargs="?", help="queue/<file>.mp4 (omit to list and pick)")
    ap.add_argument("--title", help="override the stored title")
    ap.add_argument("--publish-at", default=None,
                    help="RFC3339 UTC, e.g. 2026-06-20T14:00:00Z (omit = public now)")
    ap.add_argument("--keep", action="store_true",
                    help="leave the file in queue/ instead of moving to posted/")
    args = ap.parse_args()
    run_pipeline._load_env()

    if args.video:
        mp4 = Path(args.video)
        if not mp4.is_absolute():
            mp4 = HERE / args.video
    else:
        vids = _list()
        if not vids:
            return
        choice = input("\nNumber to publish (Enter to cancel): ").strip()
        if not choice:
            print("cancelled.")
            return
        try:
            mp4 = vids[int(choice) - 1]
        except (ValueError, IndexError):
            raise SystemExit("❌ invalid selection.")

    if not mp4.exists():
        raise SystemExit(f"❌ not found: {mp4}")

    title, description, tags, theme = _meta(mp4)
    title = args.title or title
    if not title:
        raise SystemExit("❌ no title in sidecar; pass --title \"...\".")

    print(f"\npublishing {mp4.name}\n  title: {title!r}  (theme={theme})")
    result = upload_youtube.upload(mp4, title, description, tags=tags,
                                   publish_at=args.publish_at)
    if "error" in result:
        raise SystemExit(f"❌ {result['error']}")

    # Record it so analyze.py can measure this title's pull at the 24h mark.
    ledger.log_upload(result["video_id"], title, theme, result["url"])

    if not args.keep:
        POSTED.mkdir(exist_ok=True)
        mp4.rename(POSTED / mp4.name)
        sidecar = mp4.with_suffix(".json")
        if sidecar.exists():
            sidecar.rename(POSTED / sidecar.name)
        print(f"  archived to posted/{mp4.name}")


if __name__ == "__main__":
    main()
