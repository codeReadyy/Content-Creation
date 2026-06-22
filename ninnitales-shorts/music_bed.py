"""music_bed.py — lay the royalty-free lullaby across a finished (silent) Short.

One continuous track over the whole hook→CTA video, so the join is seamless and the
music never restarts mid-way. Replaces whatever (silent) audio the stitch produced.
"""

import subprocess
from pathlib import Path

HERE = Path(__file__).parent
MUSIC = HERE / "assets" / "music" / "lullaby.mp3"


def _duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def add_music(video: Path, volume: float = 0.55) -> Path:
    """Mux the lullaby under `video` (in place), trimmed to length with fades."""
    video = Path(video)
    if not MUSIC.exists():
        print("  ⚠️  assets/music/lullaby.mp3 missing — leaving the Short silent.")
        return video
    dur = _duration(video)
    fade_out = max(0.0, dur - 1.2)
    afilter = (f"atrim=0:{dur:.3f},asetpts=PTS-STARTPTS,volume={volume},"
               f"afade=t=in:st=0:d=0.5,afade=t=out:st={fade_out:.3f}:d=1.2")
    tmp = video.with_name(video.stem + "_mus.mp4")
    cmd = ["ffmpeg", "-y", "-i", str(video), "-i", str(MUSIC),
           "-filter_complex", f"[1:a]{afilter}[a]",
           "-map", "0:v", "-map", "[a]",
           "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
           "-shortest", "-movflags", "+faststart", str(tmp)]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        print("  ⚠️  music mux failed, keeping as-is:\n" + (e.stderr or "")[-400:])
        tmp.unlink(missing_ok=True)
        return video
    tmp.replace(video)
    print(f"  🎵 lullaby laid under the Short ({dur:.1f}s)")
    return video


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Lay the lullaby under a Short.")
    ap.add_argument("video")
    ap.add_argument("--volume", type=float, default=0.55)
    add_music(ap.parse_args().video, volume=ap.parse_args().volume)
