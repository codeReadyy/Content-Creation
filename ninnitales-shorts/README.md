# NinniTales Shorts — hook-stitch pipeline

Grows the NinniTales YouTube channel by dripping ≤5 Shorts/day. Each Short is a
short emotional **hook** with a NinniTales **CTA** stitched on the end, uploaded via
the free YouTube Data API.

Hooks come from two sources you can mix:
- **generated** (primary) — an original cozy-anime hook made on the fly: GPT writes
  the line, `gpt-image-1` paints the scene, ffmpeg adds motion. Safe, on-brand, free,
  zero copyright risk.
- **scraped** (optional spice) — the first ~3s of a fresh Short from channels you list,
  for trend-jacking. Has copyright exposure; use sparingly.

```
generate_hook.py  → GPT line + gpt-image-1 anime scene + caption + Ken Burns = hook
scrape_hooks.py   → first ~3s of a fresh Short (yt-dlp), dedupe by id
stitch_cta.py     → re-encode hook + CTA into one 1080x1920 30fps h264 Short
upload_youtube.py → upload to NinniTales (OAuth refresh token), optional schedule
run_pipeline.py   → orchestrates: get hook (generated|scraped|mix) → stitch → upload
cta/              → your 3 finished CTA clips (cta1/2/3.mp4)
assets/fonts/     → Anton-Regular.ttf (caption font)
channels.txt      → scrape sources (only used for --source scraped/mix)
state.json        → tracks used scraped ids (committed, so the cron dedupes)
```

## One-time setup

1. **System deps**: `brew install ffmpeg yt-dlp` (macOS) — already done on this Mac.
2. **Python deps**: `pip install -r requirements.txt`
3. **Azure image deployment (for generated hooks)**: in Azure AI Studio, deploy an
   image model (`gpt-image-1` for best quality, or `gpt-image-1-mini` to save cost).
   Then set its deployment name:
   - locally: add `NINNITALES_IMAGE_DEPLOYMENT=<your-deployment-name>` to a `.env`
     in this folder (or the AssuredReferral `.env`).
   - the chat copy reuses your existing `AZURE_OPENAI_CHAT_DEPLOYMENT`.
   - `gpt-image-1` needs api-version ≥ `2025-04-01-preview`; the generator defaults to
     that for image calls (override with `NINNITALES_IMAGE_API_VERSION`).
4. **Mint the NinniTales refresh token** (OAuth app already "In production"):
   ```
   cd ../assured-referral-autoposter
   python get_youtube_token.py --from ASSUREDREFERRAL \
       --expect-channel UCmeOOKiWH1vfdsS9XeKXJvQ
   ```
   Pick the NinniTales channel; copy the four `YOUTUBE_*_NINNITALES` values.
5. **GitHub secrets** (for the cron): `YOUTUBE_CLIENT_ID_NINNITALES`,
   `YOUTUBE_CLIENT_SECRET_NINNITALES`, `YOUTUBE_REFRESH_TOKEN_NINNITALES`,
   plus `AZURE_OPENAI_*` and `NINNITALES_IMAGE_DEPLOYMENT`. Optional `YOUTUBE_COOKIES`
   for scraped mode if Actions gets IP-blocked.

## Run it

```bash
# Generate one anime hook + CTA, don't upload (inspect queue/ first):
python run_pipeline.py --count 1 --source generated --stitch-only

# Publish one generated:
python run_pipeline.py --count 1 --source generated

# Mix generated + scraped:
python run_pipeline.py --count 2 --source mix
```

Individual stages run standalone too:
```bash
python generate_hook.py --out work/hook.mp4         # one anime hook clip
python scrape_hooks.py --out work                   # one scraped hook
python stitch_cta.py work/hook.mp4 cta/cta1.mp4 out.mp4
python upload_youtube.py out.mp4 --title "..." --description "..."
```

## The daily cron

`.github/workflows/ninnitales-daily.yml` runs at 9:00 AM IST, builds + uploads one
Short (default `--source generated`), and commits `state.json` back. Trigger it
manually from the Actions tab to test, choosing `source`, `count`, `stitch_only`.

## Content & brand knobs

- **Art style**: `ART_STYLE` constant in `generate_hook.py` (currently cozy anime /
  Ghibli). One line to restyle everything.
- **Hook angles + filter-safe rules**: `HOOK_SYSTEM` in `generate_hook.py`. Note: it
  deliberately EVOKES bedtime via setting (nightlight, empty bed, glowing speaker,
  parent silhouette) and never asks for a depicted child — image models refuse minors
  in bedroom scenes, and Azure's text filter false-trips on "child + bed".
- **CTAs**: `cta/cta1.mp4` (5s), `cta2.mp4` (5s), `cta3.mp4` (8s) — rotated round-robin.
  Drop in new `cta*.mp4` to expand.
- **Titles/description/tags**: top of `run_pipeline.py`. Generated hooks use their own
  hook line as the title automatically.

## Caveats

- **Quota**: the Cloud project is shared with AssuredReferral (10k units/day). Turn off
  AssuredReferral's YouTube auto-post to free quota.
- **Token life**: the OAuth app must stay "In production" or Google revokes the refresh
  token after 7 days.
- **Image cost**: pennies/day at 1-2 hooks. `gpt-image-1` high quality is a few cents
  per image; `mini` is cheaper.
- **Scraped copyright**: stitching others' clips can draw Content ID claims or strikes.
  Generated hooks avoid this entirely — prefer them.
