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
`--dry-run` (build, no publish) · `--account <id>` (one account).

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

## Current state (2026-06-24)
- **Formats:** `scraped_cta`, `anime_cta` (video) live; `carousel` (images) built with a
  gradient renderer + LLM slide-writer (template fallback).
- **Publishers:** `youtube` live; `instagram` (Reels + carousel, media hosted via
  `hosting.py` GitHub-release assets) is code-complete but its account is `enabled: false`
  until IG creds (`INSTAGRAM_*_<suffix>`) are added; `tiktok` is an inert seam (needs
  non-India infra + Content Posting API).
- **Analytics:** `analyze.py` aggregates winners by theme, source, `{platform}/{format}`
  surface, AND **account** — written to `analytics/winners.json`. Each account runs ONE
  format (see `config/accounts.yml`), so the per-account standings are the real head-to-head:
  to compare formats, run the same niche on two channels (one format each) and rank them.
- **Legacy:** `daily.py` is retained only for the Telegram veto-regen path; `orchestrate.py`
  is the live entry (see `.github/workflows/ninnitales-daily.yml`).
