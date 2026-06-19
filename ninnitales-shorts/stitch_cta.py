"""
stitch_cta.py — append a NinniTales CTA clip onto a scraped hook clip.

The hard part: scraped hooks come in arbitrary resolution / fps / codec, and the
CTAs are HEVC 1440x2560 @24fps. A stream-copy concat would break. So we re-encode
BOTH segments to one identical target in a single ffmpeg filter_complex pass:

    1080x1920, 30fps, h264 (yuv420p), AAC 44100 stereo

Both segments are scaled to COVER the 1080x1920 frame and then cropped (full-bleed,
no letterbox bars). Hooks that have no audio track get a generated silent track so
the concat audio stream stays continuous.
"""

import json
import subprocess
from pathlib import Path

# Output target — YouTube Shorts standard.
W, H, FPS = 1080, 1920, 30
SAR = "44100"

# Per-segment video normalization: cover the frame, then crop to exact size.
_VFILTER = (
    f"scale={W}:{H}:force_original_aspect_ratio=increase,"
    f"crop={W}:{H},setsar=1,fps={FPS},format=yuv420p"
)
_AFILTER = f"aresample={SAR},aformat=sample_fmts=fltp:channel_layouts=stereo"


def _probe(path: Path) -> dict:
    """Return ffprobe JSON for a media file."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    return json.loads(out.stdout)


def _has_audio(info: dict) -> bool:
    return any(s.get("codec_type") == "audio" for s in info.get("streams", []))


def _duration(info: dict) -> float:
    return float(info.get("format", {}).get("duration", 0.0))


def stitch(hook_path: Path, cta_path: Path, out_path: Path) -> Path:
    """
    Re-encode `hook_path` then `cta_path` into a single 1080x1920 h264 Short.

    Returns out_path on success; raises on ffmpeg failure.
    """
    hook_path, cta_path, out_path = Path(hook_path), Path(cta_path), Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    hook_info = _probe(hook_path)
    hook_has_audio = _has_audio(hook_info)
    hook_dur = _duration(hook_info)

    cmd = ["ffmpeg", "-y", "-i", str(hook_path), "-i", str(cta_path)]
    # Input indices: 0 = hook, 1 = cta. A synthetic silent source (when the hook
    # lacks audio) is appended as the next index.
    parts = [
        f"[0:v]{_VFILTER}[v0]",
        f"[1:v]{_VFILTER}[v1]",
    ]

    if hook_has_audio:
        parts.append(f"[0:a]{_AFILTER}[a0]")
    else:
        # Generate silence matching the hook's duration so the concat A stream
        # stays aligned with the V stream.
        cmd += ["-f", "lavfi", "-t", f"{hook_dur:.3f}",
                "-i", f"anullsrc=channel_layout=stereo:sample_rate={SAR}"]
        parts.append(f"[2:a]{_AFILTER}[a0]")

    parts.append(f"[1:a]{_AFILTER}[a1]")
    parts.append("[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]")

    cmd += [
        "-filter_complex", ";".join(parts),
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-r", str(FPS),
        "-c:a", "aac", "-b:a", "128k", "-ar", SAR,
        "-movflags", "+faststart",
        str(out_path),
    ]

    subprocess.run(cmd, check=True, capture_output=True, text=True)
    return out_path


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Stitch a CTA onto a hook clip.")
    ap.add_argument("hook", type=Path)
    ap.add_argument("cta", type=Path)
    ap.add_argument("out", type=Path)
    args = ap.parse_args()

    try:
        result = stitch(args.hook, args.cta, args.out)
        info = _probe(result)
        print(f"✅ {result}  ({_duration(info):.1f}s, "
              f"{info['streams'][0]['width']}x{info['streams'][0]['height']})")
    except subprocess.CalledProcessError as e:
        print("❌ ffmpeg failed:\n" + (e.stderr or "")[-2000:])
        raise
