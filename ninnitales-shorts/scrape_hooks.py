"""
scrape_hooks.py — pull the first few seconds of recent Shorts from big channels.

The hook-stitch playbook: take the opening ~3s of high-performing Shorts from
large channels, then stitch your own CTA on the end. This module fetches the
recent Shorts list for each channel in `channels.txt`, skips any video already
used (tracked in state.json), and downloads just the opening section of the next
fresh one.

yt-dlp does the heavy lifting. `--download-sections` clips at download time so we
never pull the whole video.

NOTE on running location: YouTube frequently blocks datacenter IPs (e.g. GitHub
Actions runners). If scraping fails there with 403 / "Sign in to confirm", export
cookies from a logged-in browser and pass --cookies, or run the scrape locally.
"""

import json
import subprocess
from pathlib import Path

HERE = Path(__file__).parent
CHANNELS_FILE = HERE / "channels.txt"
STATE_FILE = HERE / "state.json"

# How many seconds of the hook to keep.
HOOK_SECONDS = 3.0
# How many recent Shorts to consider per channel when picking a fresh one.
PLAYLIST_DEPTH = 30


def _load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"used_ids": []}


def _save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))


def load_channels() -> list[str]:
    """Read channel URLs/handles from channels.txt (one per line, # = comment)."""
    if not CHANNELS_FILE.exists():
        return []
    out = []
    for line in CHANNELS_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        out.append(line)
    return out


def _shorts_url(channel: str) -> str:
    """Normalize a channel handle/URL into its Shorts tab URL."""
    channel = channel.rstrip("/")
    if channel.startswith("http"):
        if channel.endswith("/shorts"):
            return channel
        return channel + "/shorts"
    if not channel.startswith("@"):
        channel = "@" + channel
    return f"https://www.youtube.com/{channel}/shorts"


def list_recent_short_ids(channel: str, cookies: str | None = None) -> list[str]:
    """Return recent Short video IDs for a channel, newest first."""
    cmd = [
        "yt-dlp", "--flat-playlist", "--print", "id",
        "--playlist-end", str(PLAYLIST_DEPTH),
    ]
    if cookies:
        cmd += ["--cookies", cookies]
    cmd.append(_shorts_url(channel))
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"  ⚠️  could not list shorts for {channel}: "
              f"{res.stderr.strip().splitlines()[-1] if res.stderr.strip() else 'unknown error'}")
        return []
    return [line.strip() for line in res.stdout.splitlines() if line.strip()]


def download_hook(video_id: str, out_path: Path, cookies: str | None = None) -> Path | None:
    """Download just the opening HOOK_SECONDS of one video. Returns path or None."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmpl = str(out_path.with_suffix(".%(ext)s"))
    cmd = [
        "yt-dlp",
        "-f", "bv*[ext=mp4][height<=1920]+ba[ext=m4a]/b[ext=mp4]/b",
        "--download-sections", f"*0-{HOOK_SECONDS}",
        "--force-keyframes-at-cuts",
        "--no-playlist",
        "--merge-output-format", "mp4",
        "-o", tmpl,
    ]
    if cookies:
        cmd += ["--cookies", cookies]
    cmd.append(f"https://www.youtube.com/watch?v={video_id}")
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"  ⚠️  download failed for {video_id}: "
              f"{res.stderr.strip().splitlines()[-1] if res.stderr.strip() else 'unknown'}")
        return None
    # yt-dlp resolves %(ext)s; find what it actually wrote.
    candidates = list(out_path.parent.glob(out_path.stem + ".*"))
    real = next((c for c in candidates if c.suffix.lower() == ".mp4"), None)
    return real or (candidates[0] if candidates else None)


def next_hook(out_dir: Path, cookies: str | None = None) -> dict | None:
    """
    Find the next unused Short across all channels, download its hook.

    Returns {"video_id", "channel", "path"} or None if nothing fresh found.
    Marks the chosen id as used in state.json.
    """
    out_dir = Path(out_dir)
    channels = load_channels()
    if not channels:
        print("❌ No channels in channels.txt — add channel handles/URLs first.")
        return None

    state = _load_state()
    used = set(state["used_ids"])

    for channel in channels:
        print(f"• scanning {channel} ...")
        for vid in list_recent_short_ids(channel, cookies):
            if vid in used:
                continue
            print(f"  → trying {vid}")
            path = download_hook(vid, out_dir / f"hook_{vid}", cookies)
            if path and path.exists():
                state["used_ids"].append(vid)
                _save_state(state)
                return {"video_id": vid, "channel": channel, "path": path}
    print("❌ No fresh Shorts found across channels (all already used?).")
    return None


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Download the next fresh hook clip.")
    ap.add_argument("--out", type=Path, default=HERE / "work")
    ap.add_argument("--cookies", default=None, help="Path to cookies.txt (optional)")
    args = ap.parse_args()

    hook = next_hook(args.out, args.cookies)
    if hook:
        print(f"✅ {hook['video_id']} from {hook['channel']} -> {hook['path']}")
