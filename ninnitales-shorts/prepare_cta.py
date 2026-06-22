"""prepare_cta.py — bake the Poppins caption onto a CLEAN (text-free) CTA clip.

You export the CTA without captions/music; this burns the conversion caption on it
in the SAME Poppins style as the hook, so the whole Short looks identical. Music is
NOT added here — the pipeline lays one continuous lullaby over the finished Short so
the hook→CTA join stays seamless. A silent audio track is added so stitch_cta (which
expects the CTA to have audio) still works.

    python prepare_cta.py "/path/to/clean_cta.mp4" --out cta/cta1.mp4

Edit BEATS to change the wording/timing, then re-run.
"""

import argparse
import json
import subprocess
from pathlib import Path

import generate_hook as gh

W, H = gh.W, gh.H  # 1080x1920

# (text, start_sec, end_sec) — timed to the clip's story (child awake → asleep).
BEATS = [
    ("A bedtime story in your own voice", 0.3, 2.6),
    ("Bedtime that finally feels like home", 2.7, 5.0),
]


def _duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def prepare(src: Path, out: Path, beats=BEATS) -> Path:
    src, out = Path(src), Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    dur = _duration(src)
    work = out.parent / "_cta_text"
    work.mkdir(exist_ok=True)

    # Render each caption beat as a Poppins overlay PNG (same style as the hook).
    pngs = []
    for i, (text, s, e) in enumerate(beats):
        p = work / f"beat{i}.png"
        gh._text_overlay(gh.clean_caption(text)).save(p)
        pngs.append((p, s, e))

    inputs = ["-i", str(src)]
    for p, _, _ in pngs:
        inputs += ["-loop", "1", "-i", str(p)]
    # Silent stereo track so the downstream stitch (expects CTA audio) is happy.
    inputs += ["-f", "lavfi", "-t", f"{dur:.3f}",
               "-i", "anullsrc=r=44100:cl=stereo"]
    audio_idx = len(pngs) + 1

    filt = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H},setsar=1[base];")
    last = "base"
    for i, (p, s, e) in enumerate(pngs):
        nxt = f"v{i}"
        filt += f"[{last}][{i+1}:v]overlay=0:0:enable='between(t,{s},{e})'[{nxt}];"
        last = nxt
    filt = filt.rstrip(";")

    cmd = ["ffmpeg", "-y", *inputs,
           "-filter_complex", filt,
           "-map", f"[{last}]", "-map", f"{audio_idx}:a",
           "-t", f"{dur:.3f}",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
           "-movflags", "+faststart", str(out)]
    subprocess.run(cmd, check=True, capture_output=True, text=True)

    for p, _, _ in pngs:
        p.unlink(missing_ok=True)
    work.rmdir()
    print(f"✅ captioned CTA → {out}  ({dur:.1f}s)")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Bake Poppins caption onto a clean CTA.")
    ap.add_argument("src", help="path to the clean (text-free) CTA mp4")
    ap.add_argument("--out", default="cta/cta1.mp4")
    args = ap.parse_args()
    prepare(args.src, args.out)
