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

## Current state (2026-07-22)
- **Formats:** `anime_cta` (YouTube) + `scraped_cta` (Instagram) + `carousel` (IG,
  flashcard renderer + LLM slide-writer) live. Carousel theme, engagement CTA, hook
  type AND the Shorts **title shape** are all ASSIGNED in code (explore/exploit over
  winners.json) — never left to the LLM's habit. Left free it always collapses to one
  arm: GPT picked `number_promise` 14/14 on carousels, and opened 82% of 72 Shorts
  with a digit once the prompt told it listicles "work best".
- **YouTube is on ORIGINAL video since 2026-07-22.** The channel published ~35 scraped
  Shorts between Jun 30 and Jul 21 without one clearing 20 views, while the *same*
  `scraped_cta` build ran a median ~115 on Instagram over the same window — identical
  asset, identical code, 38x apart. That is a channel-level distribution verdict, not a
  content-quality gradient, and it is what YouTube's reused-content policy does to a
  channel whose every upload is 5s of someone else's Short. Posting less of it (the
  recovery cadence) cannot clear that verdict, so `ninnitales_yt_main` now runs
  `anime_cta`. The old "proven ~50x winner" note in accounts.yml was an AVERAGE carried
  by five June breakouts; on median `anime_cta` was already ahead (7.0 vs 3.0).
  `scraped_cta` stays live on Instagram, where it demonstrably works.
- **Video anatomy (both formats, 2026-07-22):** 5s hook + 0.25s crossfade + ~5.1s CTA
  tail. Caption BEATS are shared by both paths via `generate_hook.plan_beats`: the
  title's promise from second 0, then a VALUE BEAT at ~55% — one real numbered tip from
  the post's list (never the brand step; `_beat_tip` skips voice/ninnitales markers) —
  so a Short is promise → value → signature. The generated path was a single static
  title for its whole length until the beats were shared; its hook was also 3.5s, which
  made the fixed CTA 59% of every upload AND sat under `MIN_BEAT_CLIP_SECONDS`, so no
  beat could ever fire. The CTA tail rotates (`cta/cta1-3.mp4`), logged as `cta_clip`
  and ranked in winners `cta_clips`; its index counts THIS ACCOUNT's posts (it counted
  all ledger rows, so IG+Pinterest volume spun YouTube's arm). When a platform's
  watchdog verdict is `suppressed`, orchestrate thins YouTube to 1 upload/day.
- **Publishers:** `youtube` + `instagram` (Reels + carousel via `hosting.py`
  GitHub-release assets) + `pinterest` (RSS auto-publish) live; `tiktok` inert seam.
- **Analytics → strategy (the loop):** `analyze.py` measures posts (~24h) and writes
  `analytics/winners.json`; `analytics/strategy.py` turns surface standings into a
  per-slot FORMAT MIX that `orchestrate.py` samples for multi-format accounts (dead
  surface → 20% probe; that's how IG went reels-heavy when carousels measured reach
  1-2). Posts that never left the bubble (IG reach < 25, YT views < 20) are EXCLUDED
  from theme/hook/CTA standings — the loop must not learn from noise.
  `analytics/followers.json` snapshots the real KPI daily — IG followers AND (since
  Jul 22) YouTube subscribers; `analytics/strategy.json` + the Telegram digest record
  the verdict (suppressed/healthy) and the current mix.
- **Learning while suppressed (`strategy.content_rows`, Jul 22).** That noise guard
  deadlocks a platform that is suppressed WHOLESALE: nothing clears the floor, so the
  standings freeze at whatever was measured before the throttle and the picker keeps
  exploiting it. YouTube's sat on five June breakouts for three weeks while 35 posts
  published to nobody, and `carousel_hooks`/`carousel_ctas` were empty `{}` for the
  same reason. So when a platform's verdict is `suppressed`, content standings rank
  RELATIVELY inside its last 40 posts — a row's score is its percentile there, which is
  scale-free (a 4-view post outranks a 0-view post without anyone claiming 4 is good)
  and keeps a 0-view theme's weight nonzero instead of excluding it from `rng.choices`
  forever. Guards: the window needs ≥10 rows and ≥4 views of spread, or it returns
  nothing and the picker explores uniformly. `winners.json.learning_basis` records
  which basis each platform used; everything reverts to the absolute floor on recovery.
- **`search_views` is NOT search views.** `analyze._score` falls back to total views,
  and YouTube's Analytics scope has never once reported for this channel — so every
  `*_search_views` key in winners.json is a copy of the plain view count, and the
  "search-first title" thesis has never been measured (the Jul-3 audit put search at
  ~3% of traffic anyway). `winners.json.search_analytics_live` says whether to believe
  those keys. Don't reintroduce search-first title advice into the ghostwriter prompt.
- **Title dedup is fuzzy, not exact** (`run_pipeline.too_similar`). Exact-string
  matching let "5 ways to calm your overtired toddler before bedtime" and "5 simple
  ways to help your toddler calm down before bed" publish on consecutive days. Overlap
  coefficient over content words (≥0.6 of the shorter title) catches the paraphrase;
  Jaccard does not, because padding words dilute it.
- **Persist races:** concurrent crons commit the same JSON state; workflow persist
  steps must use `analytics/git_merge_json.py` (fetch → domain-merge → re-commit),
  NEVER `git pull --rebase || true` (it silently lost published posts' ledger rows).
  All SIX ninnitales workflows use the safe pattern as of Jul 22 — only `analyze` and
  `instagram` had been migrated; `daily` (the job that logs the uploads), `pinterest`
  (5 ledger appends/day), `engage` and `telegram-poll` (writes vetoes) were still on
  the banned one, all four appending to the same `ledger.json`.
- **Legacy:** `daily.py` is retained only for the Telegram veto-regen path; `orchestrate.py`
  is the live entry (see `.github/workflows/ninnitales-daily.yml`).
