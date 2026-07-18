# NinniTales content engine — how it's built (read this first)

A modular, config-driven engine that builds content in several **formats** and posts it
to many **accounts** across **platforms**, for one or more **products** — fully
autonomous (no per-post approval; guardrails replace the human veto).

## The four plugin types (one job each)

| Thing | Lives in | Contract |
|---|---|---|
| **Format** | `formats/*.py` | `build(niche, ctx) -> Asset` — makes a video or a carousel |
| **Publisher** | `publishers/*.py` | `publish(asset, copy, account, publish_at) -> {post_id,url}` |
| **Account** | `config/accounts.yml` | a (platform, account) target: niche, formats, schedule, gate |
| **Niche** | `config/niches/*.yml` | the content profile: voice, themes, CTA, titles, ghostwriter prompt |

`core/models.py` defines the types (`Asset`, `PostCopy`, `Niche`, `Account`,
`BuildContext`, and the `Format`/`Publisher` protocols). `core/config.py` loads the YAML.
`orchestrate.py` is the only thing that ties them together — **config is the source of
truth; logic never hunts across files for "who posts what."**

## The run (orchestrate.py)
For each enabled account × its scheduled slots: pick a format the platform accepts →
`format.build()` → `copywriter.compose()` (platform-tailored title/caption) →
`guardrails.check()` → `publisher.publish()` (scheduled) → `ledger.log_upload()`.
Token health is checked once up front and reported to Telegram; a dead token aborts.

Modes: `python orchestrate.py` (live) · `--plan` (decisions only, no build/publish) ·
`--dry-run` (build, no publish) · `--outbox` (build + stash to `outbox/` for MANUAL
posting — no API publish/creds; used for Pinterest while the app is on Trial access) ·
`--account <id>` (one account).

## To add X, do Y
- **A new account** → add a block to `config/accounts.yml` (set `enabled: true`). Nothing else.
- **A new niche** → add `config/niches/<name>.yml` (copy an existing one) and point an account at it.
- **A new product** → it's just a niche + accounts: add `config/niches/<product>.yml` and
  account blocks with that `product`/`niche`. (Forking the repo per product also works.)
- **A new format** → add `formats/<name>.py` with a class implementing `Format`
  (`name`, `produces`, `build`) that calls `register(...)`; add the module to
  `formats/base.py::_MODULES`. Reuse `stitch_cta`, `music_bed`, `generate_hook`,
  `scrape_hooks` as needed.
- **A new platform** → add `publishers/<platform>.py` implementing `Publisher`
  (`platform`, `accepts`, `publish`) + `register(...)`; add to `publishers/base.py::_MODULES`.
  Resolve creds by `account.creds_env` suffix (see `publishers/youtube.py`).

## Autonomy + safety
- `gate: false` (default) = autonomous. `gate: true` = a Telegram veto preview is sent
  (use for a brand-new account/format until it's proven, then flip to false).
- `core/guardrails.py` runs before every publish: media present, duration/carousel/caption
  limits per platform, brand-safety lint (extend per niche via `forbidden_phrases:`).
  A failure SKIPS the slot + raises a Telegram alert — it never posts junk.
- `token_doctor.py` diagnoses the YouTube token; the orchestrator pings Telegram every run.

## Current state (2026-07-18)
- **Formats:** `scraped_cta`, `anime_cta` (video) live; `carousel` (flashcard renderer +
  LLM slide-writer, template fallback) live. Carousel theme, engagement CTA AND hook
  type are all ASSIGNED in code (explore/exploit over winners.json) — never left to the
  LLM's habit (left free, GPT picked number_promise 14/14 and the A/B had one arm).
- **Scraped video anatomy (2026-07-18):** 5s hook (was 3s) with caption BEATS burned
  on-screen (`generate_hook.burn_caption`): the keyword promise from second 0, then a
  VALUE BEAT at ~55% — one real numbered tip from the post's list (never the brand
  step; `_beat_tip` skips voice/ninnitales markers) — so the clip is
  promise → value → signature, not clip + ad. 0.25s crossfade into a ROTATING CTA
  tail (`cta/cta1-3.mp4`; the arm is logged as `cta_clip` and ranked in winners
  `cta_clips`). Scrape channel order is
  a weighted shuffle over the hook-source standings (`scrape_hooks.channel_order`) —
  file order used to hand one channel 16 straight posts. When a platform's watchdog
  verdict is `suppressed`, orchestrate thins YouTube to 1 upload/day (recovery
  cadence) until feed tests return.
- **Publishers:** `youtube` + `instagram` (Reels + carousel via `hosting.py`
  GitHub-release assets) + `pinterest` (RSS auto-publish) live; `tiktok` inert seam.
- **Analytics → strategy (the loop):** `analyze.py` measures posts (~24h) and writes
  `analytics/winners.json`; `analytics/strategy.py` turns surface standings into a
  per-slot FORMAT MIX that `orchestrate.py` samples for multi-format accounts (dead
  surface → 20% probe; that's how IG went reels-heavy when carousels measured reach
  1-2). IG posts that never left the follower bubble (`distributed: false`, reach < 25)
  are EXCLUDED from theme/hook/CTA standings — the loop must not learn from noise.
  `analytics/followers.json` snapshots the real KPI daily; `analytics/strategy.json` +
  the Telegram digest record the verdict (suppressed/healthy) and the current mix.
- **Persist races:** concurrent crons commit the same JSON state; workflow persist
  steps must use `analytics/git_merge_json.py` (fetch → domain-merge → re-commit),
  NEVER `git pull --rebase || true` (it silently lost published posts' ledger rows).
- **Legacy:** `daily.py` is retained only for the Telegram veto-regen path; `orchestrate.py`
  is the live entry (see `.github/workflows/ninnitales-daily.yml`).
