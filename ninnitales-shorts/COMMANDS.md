# NinniTales engine — command cheatsheet

Every command you'll need, and what it does. **Run all of these from the
`ninnitales-shorts/` directory** unless noted. (Connect-helper commands run from
`connect-helper/`.)

Credentials are read from `ninnitales-shorts/.env` automatically.

---

## 📌 Pinterest — right now (manual posting, while on Trial access)

The Pinterest app is on **Trial access**, so the API can't publish pins yet. Use
`--outbox` to generate everything and post by hand until **Standard access** is approved.

| Command | What it does |
|---|---|
| `python orchestrate.py --platform pinterest --outbox --now 6` | Generate **6 pins** into `outbox/<date>/` — each an image (`.png`) + a copy-paste `.txt` (title, description, board, link, hashtags). No API, no creds needed. |
| `python orchestrate.py --platform pinterest --outbox --now 1` | Same, but just **1 pin** (quick test). |
| `open outbox` | Open the outbox folder (macOS) to grab the files. |
| `cat outbox/index.csv` | See a running log of every pin generated. |

**To post one:** open Pinterest → **Create Pin** → upload the `.png` → paste title +
description + link from the matching `.txt` → pick the board it named → Publish.

---

## 📌 Pinterest — after Standard access is approved (fully automatic)

No code changes needed — just stop using `--outbox`.

| Command | What it does |
|---|---|
| `python orchestrate.py --platform pinterest --now 6` | Build + **publish 6 pins live** via the API, rotating across boards. |
| `python orchestrate.py --platform pinterest --now 1` | Publish 1 pin live (smoke test). |
| *(automatic)* | The `.github/workflows/ninnitales-pinterest.yml` cron posts ~6 pins/day on its own. |

---

## 🔌 Connect / manage accounts (connect-helper)

Run from the **`connect-helper/`** folder.

| Command | What it does |
|---|---|
| `python app.py` | Open the local web page (`https://localhost:8765`) to **connect** YouTube / Instagram / Pinterest (OAuth → writes tokens to `.env` + GitHub secrets) and **manage** accounts (format, schedule, on/off, disconnect) — no YAML editing. |

> Re-connecting with the **same label** refreshes an expiring token. Pinterest label must
> normalize to `NINNITALES` to match the `pinterest_ninnitales` account.

---

## ▶️ Daily run (all platforms) — orchestrate.py

The main entry point. Reads `config/accounts.yml` and runs each enabled account.

| Command | What it does |
|---|---|
| `python orchestrate.py` | **Live run** — build + publish for every enabled account on its schedule. |
| `python orchestrate.py --plan` | Print the decisions only (who posts what, when). No build, no publish, no creds. |
| `python orchestrate.py --dry-run` | Build the media into `queue/` but **don't publish**. |
| `python orchestrate.py --outbox` | Build + **stash to `outbox/` for manual posting** (no API/creds). |
| `python orchestrate.py --account <id>` | Restrict to one account, e.g. `--account pinterest_ninnitales`. |
| `python orchestrate.py --platform <name>` | Restrict to one platform: `youtube` \| `instagram` \| `pinterest` \| `tiktok`. |
| `python orchestrate.py --now N` | Post **N items immediately** (ignore the schedule) — for platforms without native scheduling (Instagram, Pinterest). |

Flags combine, e.g. `--platform pinterest --outbox --now 6`.

---

## 📊 Analytics — analyze.py

| Command | What it does |
|---|---|
| `python analyze.py` | Measure posts ≥24h old (views / clicks / saves), pick winning themes → `analytics/winners.json`, send the Telegram digest. |
| `python analyze.py --min-age 12` | Only measure posts at least **12 hours** old. |
| `python analyze.py --report` | Print current standings from existing data — **don't re-measure**. |
| `python analyze.py --no-telegram` | Run without sending the Telegram digest. |

> The daily `ninnitales-analyze.yml` cron runs this automatically.

---

## 🎬 YouTube Shorts (standalone) — run_pipeline.py

| Command | What it does |
|---|---|
| `python run_pipeline.py --count 1 --source generated` | Make + upload **1 generated** (AI anime) Short. |
| `python run_pipeline.py --count 2 --source mix` | Make 2 Shorts, mixing **generated + scraped** hooks. |
| `python run_pipeline.py --count 1 --source scraped` | Use a **scraped** hook clip (trend-jacking). |
| `python run_pipeline.py --count 1 --source generated --stitch-only` | Build the Short into `queue/` but **don't upload** (inspect first). |

Individual stages: `python generate_hook.py --out work/hook.mp4` · `python
scrape_hooks.py --out work` · `python stitch_cta.py work/hook.mp4 cta/cta1.mp4 out.mp4` ·
`python upload_youtube.py out.mp4 --title "..." --description "..."`.

---

## 🩺 Health / token checks

| Command | What it does |
|---|---|
| `python token_doctor.py` | Diagnose the **YouTube** token (alive? scopes? channel?). |
| `python token_doctor.py --expect-channel <CHANNEL_ID>` | Same, and warn if it's not the expected channel. |
| `python orchestrate.py --platform pinterest --plan` | Fast wiring check for Pinterest (no creds touched). |
| Pinterest token (advanced) | `python -c "import token_doctor as t; print(t.check_pinterest('NINNITALES'))"` — is the Pinterest token alive? (Also checked automatically at the start of every live Pinterest run.) |

---

## ⚙️ One-time setup

| Command | What it does |
|---|---|
| `pip install -r requirements.txt` | Install engine dependencies (run in `ninnitales-shorts/`). |
| `pip install -r requirements.txt` *(in `connect-helper/`)* | Install connect-helper dependencies. |
| `gh auth login` | Authenticate the GitHub CLI so the connect-helper can write repo secrets. |
| `brew install ffmpeg yt-dlp` | System deps for video Shorts (not needed for Pinterest pins). |

---

## Where things land

| Path | What |
|---|---|
| `outbox/<date>/` | Pins to post manually (`.png` + `.txt`), + `outbox/index.csv` log. |
| `queue/` | Built media from live/dry-run. |
| `analytics/ledger.json` | Every published post + its measured stats. |
| `analytics/winners.json` | Winning themes/accounts the engine doubles down on. |
| `config/accounts.yml` | Which accounts post what, when (the routing table). |
| `config/niches/toddler_sleep.yml` | Brand voice, themes, boards, links. |
