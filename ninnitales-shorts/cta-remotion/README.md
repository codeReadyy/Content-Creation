# NinniTales CTA (Remotion)

The fixed ~7-second CTA clip that gets stitched onto every scraped hook. One clip,
reused on every video.

## Run it

```bash
cd ninnitales-shorts/cta-remotion
npm install            # one time (needs Node 18+; install from nodejs.org)
npm start              # opens Remotion Studio in the browser to preview/scrub
npm run render         # renders to out/cta.mp4 (1080x1920, h264)
```

It previews immediately with gradient backgrounds and the text animation — no
assets required to start.

## Customize

Everything is in `src/CTA.tsx` -> `CTA_CONFIG` at the top:

- `music`: drop a song into `public/` and put its filename here.
- `beats[].image`: drop images into `public/` and reference filenames.
- `beats[].lines`: the on-screen copy per beat.
- `beats[2].brand` / `.cta`: the end-card wordmark + call to action.

Beat timing and cross-fades are in `BEAT_WINDOWS` (frames at 30fps, 210 total).

## The creative intent

1. **0–2.6s the ache** — a parent away at bedtime. Emotional pattern-interrupt so
   the brainrot-hook viewer doesn't swipe.
2. **2.6–5s the magic** — the kid hears the parent's own voice. The whole product
   in one shot.
3. **5–7s promise + CTA** — "You can't always be there. Your voice can." +
   NinniTales + how to find it.

Swap the placeholder copy/colors for your brand. Real phone footage of a parent +
kid converts better than stock — worth filming once.

## Output

`out/cta.mp4` is the asset the stitch step (`stitch_cta.py`) appends to every hook.
