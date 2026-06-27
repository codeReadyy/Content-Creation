"""app.py — the local "Connect" + manage web page.

Run it, open the page, and from one screen:
  • Connect a YouTube / Instagram account (OAuth → tokens auto-written to BOTH the engine's
    .env and the matching GitHub secret → an account block scaffolded in accounts.yml).
  • Manage every account WITHOUT touching YAML: pick its format, edit its schedule,
    enable/disable it, or disconnect it (which deletes its tokens from .env + GitHub and
    removes the block).

Instagram uses the "Instagram API with Instagram login" path (no Facebook Page). That API
requires an HTTPS redirect, so the helper serves HTTPS with a self-signed cert by default —
your browser warns once; click through (it's your own localhost).

Standalone by design — it never imports ninnitales-shorts code; it only writes the engine's
.env / accounts.yml and GitHub secrets (see store.py, accounts.py).

    cd connect-helper
    pip install -r requirements.txt
    gh auth login            # one-time, so GitHub secrets can be written
    python app.py
"""

from __future__ import annotations

import html
import re
import secrets as _secrets
import webbrowser
from pathlib import Path

from flask import Flask, redirect, request

import accounts
import config
import store
from oauth import google, meta

app = Flask(__name__)

# Short-lived in-memory state for the OAuth round-trips (localhost, single user).
_PENDING: dict[str, dict] = {}   # state -> {"platform", "label"}


# ── helpers ───────────────────────────────────────────────────────────────────
def _suffix(label: str) -> str:
    """Normalize a user label into an env-var SUFFIX, e.g. 'Acct A' -> 'ACCT_A'."""
    return re.sub(r"[^A-Za-z0-9]+", "_", label).strip("_").upper()


def _read_env() -> dict[str, str]:
    """Source-of-truth values from the engine's .env file (not os.environ)."""
    path: Path = config.TARGET_ENV
    out: dict[str, str] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.split("#", 1)[0].strip()
            if line and "=" in line:
                k, _, v = line.partition("=")
                out[k.strip()] = v.strip()
    return out


def _secret_keys(platform: str, suffix: str) -> list[str]:
    if platform == "youtube":
        return [f"YOUTUBE_CLIENT_ID_{suffix}", f"YOUTUBE_CLIENT_SECRET_{suffix}",
                f"YOUTUBE_REFRESH_TOKEN_{suffix}"]
    if platform == "instagram":
        return [f"INSTAGRAM_ACCESS_TOKEN_{suffix}",
                f"INSTAGRAM_BUSINESS_ACCOUNT_ID_{suffix}"]
    return []


def _connected(platform: str, suffix: str, env: dict) -> bool:
    if platform == "youtube":
        return f"YOUTUBE_REFRESH_TOKEN_{suffix}" in env
    if platform == "instagram":
        return f"INSTAGRAM_ACCESS_TOKEN_{suffix}" in env
    return False


def _parse_times(raw: str) -> list[str]:
    """Comma/space separated HH:MM -> validated list (drops anything malformed)."""
    return [t for t in (p.strip() for p in re.split(r"[,\s]+", raw)) if accounts.TIME_RE.match(t)]


def layout(title: str, body: str) -> str:
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>{html.escape(title)}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font: 15px/1.5 system-ui, sans-serif; max-width: 940px; margin: 2.5rem auto;
         padding: 0 1.2rem; }}
  h1 {{ font-size: 1.5rem; }} h2 {{ font-size: 1.1rem; margin-top: 2rem; }}
  .btn {{ display: inline-block; padding: .6rem 1rem; border-radius: 8px; color: #fff;
         text-decoration: none; font-weight: 600; margin-right: .5rem; border: 0;
         cursor: pointer; font-size: 1rem; }}
  .yt {{ background: #c4302b; }} .ig {{ background: #c13584; }} .muted {{ opacity: .65; }}
  .card {{ border: 1px solid #8884; border-radius: 10px; padding: 1rem 1.2rem; margin: 1rem 0; }}
  .ok {{ color: #1a7f37; }} .bad {{ color: #c4302b; }}
  .s {{ padding: .25rem .55rem; border-radius: 6px; border: 1px solid #8886; cursor: pointer;
       background: transparent; font: inherit; }}
  .link {{ background: 0; border: 0; padding: 0; color: #c4302b; cursor: pointer;
          text-decoration: underline; font: inherit; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ text-align: left; padding: .45rem .55rem; border-bottom: 1px solid #8883;
           vertical-align: middle; }}
  input, select {{ padding: .35rem .5rem; border-radius: 6px; border: 1px solid #8886;
                  font: inherit; }}
  code {{ background: #8881; padding: .1rem .3rem; border-radius: 4px; }}
  form.inline {{ display: inline; }}
</style></head><body>{body}
<p class="muted" style="margin-top:3rem">connect-helper · writes to <code>{html.escape(str(config.TARGET_ENV))}</code> + GitHub secrets</p>
</body></html>"""


def _account_table() -> str:
    env = _read_env()
    rows = []
    for a in accounts.list_accounts():
        plat, aid, suffix = a["platform"], a["id"], a["creds_env"]
        conn = _connected(plat, suffix, env)
        conn_html = ('<span class="ok">● connected</span>' if conn
                     else '<span class="muted">○ no token</span>')
        # format dropdown (auto-submits)
        opts = accounts.FORMATS_BY_PLATFORM.get(plat, [])
        cur = a["formats"][0] if a["formats"] else ""
        sel = "".join(f'<option {"selected" if f == cur else ""}>{f}</option>' for f in opts)
        fmt_form = (f'<form class="inline" method="post" action="/account/{aid}/format">'
                    f'<select class="s" name="format" onchange="this.form.submit()">{sel}'
                    f'</select></form>')
        # schedule
        sched_form = (f'<form class="inline" method="post" action="/account/{aid}/schedule">'
                      f'<input name="times" size="16" value="{", ".join(a["schedule_et"])}">'
                      f'<button class="s">save</button></form>')
        # enable/disable
        on = a["enabled"]
        en_form = (f'<form class="inline" method="post" action="/account/{aid}/enabled">'
                   f'<input type="hidden" name="enabled" value="{0 if on else 1}">'
                   f'<button class="s">{"✅ on — disable" if on else "⏸ off — enable"}</button>'
                   f'</form>')
        # disconnect
        dc_form = (f'<form class="inline" method="post" action="/account/{aid}/disconnect" '
                   f'onsubmit="return confirm(\'Disconnect {aid}? This deletes its tokens from '
                   f'.env + GitHub and removes the account block.\')">'
                   f'<button class="link">disconnect</button></form>')
        rows.append(
            f"<tr><td>{plat}</td><td><code>{html.escape(aid)}</code><br>"
            f"<span class='muted'>{conn_html}</span></td>"
            f"<td>{fmt_form}</td><td>{sched_form}</td><td>{en_form}</td><td>{dc_form}</td></tr>")
    if not rows:
        return "<p class='muted'>No accounts yet — connect one above.</p>"
    return ("<table><tr><th>Platform</th><th>Account</th><th>Format</th>"
            "<th>Schedule (ET)</th><th>Status</th><th></th></tr>" + "".join(rows) + "</table>")


def _error_page(title: str, detail: str, hint: str = ""):
    """Render the real error instead of an opaque 500, so the cause is visible."""
    hint_html = f"<p>{hint}</p>" if hint else ""
    return layout(title, f"""
      <h1 class="bad">{html.escape(title)}</h1>
      <div class="card"><pre style="white-space:pre-wrap;margin:0">{html.escape(detail)}</pre>
      {hint_html}</div>
      <p><a href="/">← back</a></p>"""), 502


def _save_results_html(title: str, acct_id: str, saved: list, scaffolded: bool) -> str:
    lines = []
    for r in saved:
        env = '<span class="ok">.env ✅</span>' if r.env_ok else '<span class="bad">.env ❌</span>'
        gh = ('<span class="ok">GitHub ✅</span>' if r.gh_ok
              else f'<span class="bad">GitHub ❌ {html.escape(r.detail)}</span>')
        lines.append(f"<li><code>{r.key}</code> — {env} · {gh}</li>")
    scaf = (f"<p>Added <code>{acct_id}</code> (disabled). Set its format/schedule and enable it "
            "on the home page — no YAML needed.</p>" if scaffolded
            else f"<p class='muted'>accounts.yml already had <code>{acct_id}</code> — left as-is.</p>")
    return layout(title, f"""
      <h1>{html.escape(title)}</h1>
      <div class="card"><ul>{''.join(lines)}</ul>{scaf}</div>
      <p><a href="/">← back</a></p>""")


# ── routes ────────────────────────────────────────────────────────────────────
@app.get("/")
def home():
    warn = []
    if not store.gh_ready():
        warn.append("⚠️ <b>gh CLI not authenticated</b> — run <code>gh auth login</code> "
                    "so secrets can be written to GitHub (the .env write still works).")
    if not config.google_ready():
        warn.append("⚠️ Google client not set — add <code>GOOGLE_CLIENT_ID/SECRET</code> to "
                    "connect-helper/.env (or reuse the NinniTales client).")
    if not config.instagram_ready():
        warn.append("⚠️ Instagram app not set — add <code>INSTAGRAM_APP_ID/SECRET</code> to "
                    "connect-helper/.env (Meta app → Instagram → API setup with Instagram login).")
    warn_html = "".join(f'<div class="card">{w}</div>' for w in warn)
    repo = store.detect_repo() or "(unknown repo)"
    body = f"""
      <h1>🔌 Accounts</h1>
      <p class="muted">Connect once; manage everything here. Tokens write to the engine's
      <code>.env</code> + the <code>{html.escape(repo)}</code> GitHub secrets in one step.</p>
      {warn_html}
      <form action="/connect/google" method="get" class="inline">
        <input name="label" placeholder="label, e.g. yt_main" required>
        <button class="btn yt">Connect YouTube</button>
      </form>
      <form action="/connect/instagram" method="get" class="inline" style="margin-left:.5rem">
        <input name="label" placeholder="label, e.g. ig_main" required>
        <button class="btn ig">Connect Instagram</button>
      </form>
      <h2>Manage accounts</h2>
      {_account_table()}"""
    return layout("Accounts — content engine", body)


@app.get("/connect/google")
def connect_google():
    if not config.google_ready():
        return layout("Not configured", "<p>Set GOOGLE_CLIENT_ID/SECRET first.</p>"), 400
    state = _secrets.token_urlsafe(16)
    _PENDING[state] = {"platform": "google", "label": request.args["label"]}
    return redirect(google.auth_url(state))


@app.get("/connect/instagram")
def connect_instagram():
    if not config.instagram_ready():
        return layout("Not configured", "<p>Set INSTAGRAM_APP_ID/SECRET first.</p>"), 400
    state = _secrets.token_urlsafe(16)
    _PENDING[state] = {"platform": "instagram", "label": request.args["label"]}
    return redirect(meta.auth_url(state))


@app.get("/callback/google")
def cb_google():
    pend = _PENDING.pop(request.args.get("state", ""), None)
    if request.args.get("error") or not pend:
        return layout("Failed", f"<p class='bad'>OAuth error: "
                      f"{html.escape(request.args.get('error', 'bad state'))}</p>"), 400
    try:
        tokens = google.exchange_code(request.args["code"])
        refresh = tokens.get("refresh_token")
        if not refresh:
            return layout("Failed", "<p class='bad'>No refresh_token returned. Revoke prior "
                          "access at myaccount.google.com/permissions and retry.</p>"), 400
        _, title = google.channel_identity(tokens.get("access_token", ""))
        suffix = _suffix(pend["label"])
        saved = [
            store.save_secret(f"YOUTUBE_CLIENT_ID_{suffix}", config.GOOGLE_CLIENT_ID),
            store.save_secret(f"YOUTUBE_CLIENT_SECRET_{suffix}", config.GOOGLE_CLIENT_SECRET),
            store.save_secret(f"YOUTUBE_REFRESH_TOKEN_{suffix}", refresh),
        ]
        wrote, acct_id = accounts.scaffold("youtube", suffix, identity=title)
    except Exception as e:
        return _error_page("YouTube connect failed", f"{type(e).__name__}: {e}")
    return _save_results_html(f"YouTube connected: {title or suffix}", acct_id, saved, wrote)


@app.get("/callback/instagram")
def cb_instagram():
    pend = _PENDING.pop(request.args.get("state", ""), None)
    if request.args.get("error") or not pend:
        msg = request.args.get("error_description") or request.args.get("error") or "bad state"
        return layout("Failed", f"<p class='bad'>OAuth error: {html.escape(msg)}</p>"), 400
    try:
        short, _ = meta.exchange_code(request.args["code"])
        token, _ = meta.long_lived(short)
        ig_id, username = meta.identity(token)
    except Exception as e:
        return _error_page(
            "Instagram connect failed", f"{type(e).__name__}: {e}",
            hint="If this mentions an invalid scope/permission, add "
                 "<code>instagram_business_manage_insights</code> in your Meta app "
                 "(Instagram → API setup with Instagram login → Permissions) and retry — "
                 "or tell me to drop the insights scope to connect without it.")
    if not ig_id:
        return layout("Failed", "<p class='bad'>Could not read the Instagram account. Make "
                      "sure it's a Business/Creator account and retry.</p>"), 400
    suffix = _suffix(pend["label"])
    try:
        saved = [
            store.save_secret(f"INSTAGRAM_ACCESS_TOKEN_{suffix}", token),
            store.save_secret(f"INSTAGRAM_BUSINESS_ACCOUNT_ID_{suffix}", ig_id),
        ]
        wrote, acct_id = accounts.scaffold("instagram", suffix, identity=f"@{username}")
    except Exception as e:
        return _error_page("Instagram save failed", f"{type(e).__name__}: {e}")
    return _save_results_html(f"Instagram connected: @{username}", acct_id, saved, wrote)


# ── manage (no YAML editing needed) ─────────────────────────────────────────────
def _platform_of(acct_id: str) -> str | None:
    for a in accounts.list_accounts():
        if a["id"] == acct_id:
            return a["platform"]
    return None


@app.post("/account/<aid>/format")
def set_format(aid):
    plat = _platform_of(aid)
    fmt = request.form.get("format", "")
    if plat and fmt in accounts.FORMATS_BY_PLATFORM.get(plat, []):
        accounts.set_format(aid, fmt)
    return redirect("/")


@app.post("/account/<aid>/enabled")
def set_enabled(aid):
    accounts.set_enabled(aid, request.form.get("enabled") == "1")
    return redirect("/")


@app.post("/account/<aid>/schedule")
def set_schedule(aid):
    times = _parse_times(request.form.get("times", ""))
    if times:
        accounts.set_schedule(aid, times)
    return redirect("/")


@app.post("/account/<aid>/disconnect")
def disconnect(aid):
    acct = next((a for a in accounts.list_accounts() if a["id"] == aid), None)
    if acct:
        for key in _secret_keys(acct["platform"], acct["creds_env"]):
            store.remove_secret(key)
        accounts.remove(aid)
    return redirect("/")


if __name__ == "__main__":
    print(f"\n  Connect helper → {config.BASE_URL}")
    if config.USE_HTTPS:
        print("  (self-signed HTTPS — your browser will warn once; click through)\n")
    webbrowser.open(config.BASE_URL)
    app.run(port=config.PORT, debug=False,
            ssl_context="adhoc" if config.USE_HTTPS else None)
