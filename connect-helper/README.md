# connect-helper

A tiny **local** web app that links a YouTube or Instagram account to the content engine
in one click. You log in once in the browser; it writes the OAuth tokens to **both** the
engine's `.env` **and** the matching **GitHub repo secret** — so the local and cloud copies
can never drift apart (the drift that used to silently revoke this project's tokens). It
also scaffolds an `enabled: false` block in `config/accounts.yml` for the new account.

This is **Phase 1**. It's deliberately standalone — it never imports engine code, only
writes files the engine reads — so it's easy to grow into the Phase 2 hosted dashboard.

## One-time setup

```bash
cd connect-helper
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then fill it in (below)
gh auth login                 # so the helper can write GitHub secrets
```

> **HTTPS:** Instagram's API requires an HTTPS redirect, so the helper serves
> **self-signed HTTPS** by default (`https://localhost:8765`). Your browser will warn once
> ("not private") — click through; it's your own machine. (YouTube-only? You can set
> `CONNECT_HTTPS=0` and use plain http.)

### `.env`
- **Google/YouTube:** reuse your existing NinniTales OAuth client — set `GOOGLE_CLIENT_ID`
  / `GOOGLE_CLIENT_SECRET` (or leave blank to auto-borrow `YOUTUBE_CLIENT_ID_NINNITALES`
  from `../ninnitales-shorts/.env`).
- **Instagram:** set `INSTAGRAM_APP_ID` / `INSTAGRAM_APP_SECRET` (the *Instagram* app
  id/secret — see below).

### Google OAuth client (Cloud Console → APIs & Services → Credentials)
On your **Web application** client, add this **Authorized redirect URI**:
`https://localhost:8765/callback/google` (keep any existing `http://localhost...` too).

### Instagram via "Instagram API with Instagram login" (developers.facebook.com)
You still need a (free) **Facebook account** to create the app, but your IG accounts do
**not** need a Facebook Page on this path.
1. Set each Instagram account to **Professional (Business or Creator)** — Instagram app →
   Settings → Account type. (Free.)
2. developers.facebook.com → **Create App** → use case **"Manage everything on your
   Instagram account"** (adds the Instagram product).
3. App → **Instagram → API setup with Instagram login**:
   - copy the **Instagram app ID** + **Instagram app secret** → into `connect-helper/.env`
     as `INSTAGRAM_APP_ID` / `INSTAGRAM_APP_SECRET`.
   - under **Business login settings**, add OAuth redirect URI:
     `https://localhost:8765/callback/instagram`.
   - add **Instagram business accounts** as testers (and accept the invite in the IG app)
     so Dev Mode can post to your own accounts — no full App Review for self-use.
4. Permissions used: `instagram_business_basic`, `instagram_business_content_publish`.

## Run it

```bash
python app.py          # opens https://localhost:8765 (accept the self-signed cert)
```

Type a short label (e.g. `yt_main`), click **Connect YouTube** / **Connect Instagram**,
finish the login. The result page shows each secret written to `.env` ✅ and GitHub ✅.

## Manage accounts (no YAML)

The home page lists every account with inline controls — all of which edit
`../ninnitales-shorts/config/accounts.yml` for you (round-trip, comments preserved):
- **Format** — dropdown (only the formats that platform can post); one per account.
- **Schedule (ET)** — comma-separated `HH:MM` times; bad entries are dropped.
- **Status** — toggle the account **on/off** (`enabled`).
- **Disconnect** — deletes the account's tokens from `.env` **and** GitHub, and removes
  its block. (Confirms first.)

Verify what the engine will do:
```bash
cd ../ninnitales-shorts && python orchestrate.py --plan
```

## Notes / limits (Phase 1)
- **Cloud uses the *committed* config + GitHub secrets.** The UI writes your LOCAL
  `accounts.yml`; secrets are pushed to GitHub live, but `accounts.yml` changes only reach
  the cloud cron after you commit + push the file. (Phase 2's DB-backed dashboard removes
  this step.)
- **`gh auth login` is required** for the GitHub half — if it's not done, you'll see a
  warning on the page and each result row shows `GitHub ❌` (the `.env` write still works).
- **Instagram tokens expire ~60 days.** Just **Connect Instagram again with the same
  label** — it mints a fresh long-lived token and overwrites the secret (no disconnect
  needed). Auto-refresh is Phase 2.
- No TikTok; single-user/local only.
- Instagram media publishing additionally needs the repo to be public (engine's
  `hosting.py`) — unrelated to connecting the account here.
