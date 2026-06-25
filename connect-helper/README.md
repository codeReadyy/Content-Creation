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

### `.env`
- **Google/YouTube:** reuse your existing NinniTales OAuth client — set `GOOGLE_CLIENT_ID`
  / `GOOGLE_CLIENT_SECRET` (or leave blank to auto-borrow `YOUTUBE_CLIENT_ID_NINNITALES`
  from `../ninnitales-shorts/.env`).
- **Meta/Instagram:** set `META_APP_ID` / `META_APP_SECRET` from your Meta app.

### Google OAuth client (Cloud Console → APIs & Services → Credentials)
Add this **Authorized redirect URI**: `http://localhost:8765/callback/google`

### Meta app (developers.facebook.com)
1. Create an app → add the **Facebook Login** product.
2. Valid OAuth redirect URI: `http://localhost:8765/callback/meta`
3. Permissions used: `instagram_basic`, `instagram_content_publish`, `pages_show_list`,
   `pages_read_engagement`, `business_management`. In **Dev Mode** these work for your OWN
   accounts (add yourself as an app admin/tester) — no full App Review needed for self-use.
4. Your IG account must be a **Business/Creator** account linked to a **Facebook Page**.

## Run it

```bash
python app.py          # opens http://localhost:8765
```

Type a short label (e.g. `yt_main`), click **Connect YouTube** / **Connect Instagram**,
finish the login. The result page shows each secret written to `.env` ✅ and GitHub ✅.

## After connecting

1. Open `../ninnitales-shorts/config/accounts.yml`, find the scaffolded block, set its
   `formats: [...]` (one format per account) + `schedule_et`, and flip `enabled: true`.
2. Verify the engine picks it up:
   ```bash
   cd ../ninnitales-shorts && python orchestrate.py --plan --account <account_id>
   ```

## Notes / limits (Phase 1)
- **Instagram tokens expire ~60 days.** Re-click **Connect Instagram** (or the *refresh*
  link on the status row) to re-extend and rewrite the secret. Auto-refresh is Phase 2.
- No scheduling/format UI yet (edit `accounts.yml`); no TikTok; single-user/local only.
- Instagram media publishing additionally needs the repo to be public (engine's
  `hosting.py`) — unrelated to connecting the account here.
