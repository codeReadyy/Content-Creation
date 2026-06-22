"""make_music.py — generate an ORIGINAL royalty-free lullaby bed (zero copyright).

A soft pentatonic music-box melody over a warm sustained pad. Pentatonic notes are
always consonant, so it stays gentle and never clashes. Output is committed as
assets/music/lullaby.mp3 and laid under the whole Short by the pipeline.

Run once (or after tweaking): python make_music.py
"""

import subprocess
from pathlib import Path

import numpy as np

SR = 44100
HERE = Path(__file__).parent
OUT = HERE / "assets" / "music" / "lullaby.mp3"

# Equal-tempered frequencies (A4=440) for the notes we use.
F = {"C3": 130.81, "E3": 164.81, "G3": 196.00, "C4": 261.63, "G4": 392.00,
     "A4": 440.00, "C5": 523.25, "D5": 587.33, "E5": 659.25, "G5": 783.99,
     "A5": 880.00, "C6": 1046.50}


def _box_note(freq: float, dur: float, decay: float = 1.1) -> np.ndarray:
    """A music-box-ish pluck: fast attack, exponential decay, a few soft harmonics."""
    t = np.arange(int(dur * SR)) / SR
    wave = (np.sin(2 * np.pi * freq * t)
            + 0.28 * np.sin(2 * np.pi * 2 * freq * t)
            + 0.12 * np.sin(2 * np.pi * 3 * freq * t))
    env = np.exp(-t / decay)
    a = int(0.004 * SR)
    env[:a] *= np.linspace(0, 1, a)
    return wave * env


def _pad(freqs: list[float], dur: float) -> np.ndarray:
    """A warm sustained chord with a slow tremolo and gentle attack/release."""
    t = np.arange(int(dur * SR)) / SR
    chord = sum(np.sin(2 * np.pi * f * t) + 0.15 * np.sin(2 * np.pi * 2 * f * t)
                for f in freqs)
    tremolo = 0.85 + 0.15 * np.sin(2 * np.pi * 0.2 * t)  # slow breathing
    env = np.ones_like(t)
    ramp = int(0.6 * SR)
    env[:ramp] = np.linspace(0, 1, ramp)
    env[-ramp:] = np.linspace(1, 0, ramp)
    return chord * tremolo * env


def build() -> np.ndarray:
    total = 13.0
    mix = np.zeros(int(total * SR))

    # Warm pad: C major, swapping to F-ish color halfway, very low in the mix.
    pad = np.concatenate([_pad([F["C3"], F["E3"], F["G3"]], 6.5),
                          _pad([F["C3"], F["G3"], F["C4"]], 6.5)])
    pad = pad[:len(mix)]
    mix[:len(pad)] += 0.10 * pad / np.max(np.abs(pad))

    # Music-box melody: a gentle meandering pentatonic line (original).
    melody = ["C5", "E5", "G5", "E5", "D5", "C5", "G4", "A4",
              "C5", "E5", "D5", "C5", "A4", "G4", "C5", "E5",
              "G5", "A5", "G5", "E5", "D5", "C5"]
    step = 0.58
    pos = 0.4
    for name in melody:
        n = _box_note(F[name], 1.3)
        i = int(pos * SR)
        end = min(i + len(n), len(mix))
        mix[i:end] += 0.5 * n[:end - i]
        pos += step

    mix /= np.max(np.abs(mix)) + 1e-9
    mix *= 0.82  # leave headroom
    # Soft global fade in/out.
    f = int(0.5 * SR)
    mix[:f] *= np.linspace(0, 1, f)
    mix[-int(1.5 * SR):] *= np.linspace(1, 0, int(1.5 * SR))
    return mix


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    audio = build()
    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()
    # Pipe raw PCM into ffmpeg → mp3.
    subprocess.run(
        ["ffmpeg", "-y", "-f", "s16le", "-ar", str(SR), "-ac", "1", "-i", "pipe:0",
         "-c:a", "libmp3lame", "-b:a", "192k", str(OUT)],
        input=pcm, check=True, capture_output=True,
    )
    print(f"✅ wrote {OUT}  ({len(audio)/SR:.1f}s)")


if __name__ == "__main__":
    main()
