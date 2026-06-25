"""app.py — the local "Connect" web page.

Run it, open http://localhost:8765, click "Connect YouTube" / "Connect Instagram",
log in once in the browser, and the helper auto-writes the tokens to BOTH the engine's
.env and the matching GitHub repo secret, then scaffolds an (enabled:false) account
block. No copy-paste, no secret drift.

Standalone by design — it never imports ninnitales-shorts code; it only writes the
engine's .env / accounts.yml and GitHub secrets (see store.py, accounts.py).

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
_RESOLVE: dict[str, dict] = {}   # key   -> {"label", "token", "igs"}  (meta IG pick)


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


def layout(title: str, body: str) -> str:
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>{html.escape(title)}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font: 15px/1.5 system-ui, sans-serif; max-width: 720px; margin: 2.5rem auto;
         padding: 0 1.2rem; }}
  h1 {{ font-size: 1.5rem; }} h2 {{ font-size: 1.1rem; margin-top: 2rem; }}
  .btn {{ display: inline-block; padding: .6rem 1rem; border-radius: 8px; color: #fff;
         text-decoration: none; font-weight: 600; margin-right: .5rem; }}
  .yt {{ background: #c4302b; }} .ig {{ background: #c13584; }} .muted {{ opacity: .65; }}
  .card {{ border: 1px solid #8884; border-radius: 10px; padding: 1rem 1.2rem; margin: 1rem 0; }}
  .ok {{ color: #1a7f37; }} .bad {{ color: #c4302b; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ text-align: left; padding: .4rem .6rem; border-bottom: 1px solid #8883; }}
  input {{ padding: .45rem .6rem; border-radius: 6px; border: 1px solid #8886; }}
  code {{ background: #8881; padding: .1rem .3rem; border-radius: 4px; }}
</style></head><body>{body}
<p class="muted" style="margin-top:3rem">connect-helper · writes to <code>{html.escape(str(config.TARGET_ENV))}</code> + GitHub secrets</p>
</body></html>"""


def _status_rows() -> str:
    env = _read_env()
    rows = []
    yt = sorted({m.group(1) for k in env
                 if (m := re.match(r"YOUTUBE_REFRESH_TOKEN_(.+)", k))})
    ig = sorted({m.group(1) for k in env
                 if (m := re.match(r"INSTAGRAM_ACCESS_TOKEN_(.+)", k))})
    for s in yt:
        access = google.access_from_refresh(env[f"YOUTUBE_REFRESH_TOKEN_{s}"]) \
            if config.google_ready() else None
        cid, title = google.channel_identity(access) if access else ("", "")
        health = f'<span class="ok">✅ {html.escape(title or cid)}</span>' if access \
            else '<span class="bad">❌ token dead — re-connect</span>'
        rows.append(f"<tr><td>YouTube</td><td><code>{s}</code></td><td>{health}</td></tr>")
    for s in ig:
        exp = meta.token_expiry(env[f"INSTAGRAM_ACCESS_TOKEN_{s}"]) \
            if config.meta_ready() else None
        health = (f'<span class="ok">✅ expires {exp}</span>' if exp
                  else '<span class="muted">token present</span>')
        rows.append(f"<tr><td>Instagram</td><td><code>{s}</code></td><td>{health}</td>"
                    f"<td><a href='/connect/meta?label={s}'>refresh</a></td></tr>")
    if not rows:
        return "<p class='muted'>No accounts connected yet.</p>"
    return ("<table><tr><th>Platform</th><th>Suffix</th><th>Status</th><th></th></tr>"
            + "".join(rows) + "</table>")


def _save_results_html(title: str, acct_id: str, saved: list, scaffolded: bool) -> str:
    lines = []
    for r in saved:
        env = '<span class="ok">.env ✅</span>' if r.env_ok else '<span class="bad">.env ❌</span>'
        gh = ('<span class="ok">GitHub ✅</span>' if r.gh_ok
              else f'<span class="bad">GitHub ❌ {html.escape(r.detail)}</span>')
        lines.append(f"<li><code>{r.key}</code> — {env} · {gh}</li>")
    scaf = (f"<p>Scaffolded <code>{acct_id}</code> in accounts.yml "
            "(<b>enabled: false</b>) — set its <code>formats</code> + schedule, then flip "
            "<code>enabled: true</code>.</p>" if scaffolded
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
    if not config.meta_ready():
        warn.append("⚠️ Meta app not set — add <code>META_APP_ID/SECRET</code> to "
                    "connect-helper/.env to enable Instagram.")
    warn_html = "".join(f'<div class="card">{w}</div>' for w in warn)
    repo = store.detect_repo() or "(unknown repo)"
    body = f"""
      <h1>🔌 Connect an account</h1>
      <p class="muted">Tokens are written to the engine's <code>.env</code> and to the
      <code>{html.escape(repo)}</code> GitHub secrets in one step.</p>
      {warn_html}
      <form action="/connect/google" method="get">
        <input name="label" placeholder="account label, e.g. yt_main" required>
        <button class="btn yt">Connect YouTube</button>
      </form>
      <form action="/connect/meta" method="get" style="margin-top:.8rem">
        <input name="label" placeholder="account label, e.g. ig_main" required>
        <button class="btn ig">Connect Instagram</button>
      </form>
      <h2>Connected accounts</h2>
      {_status_rows()}"""
    return layout("Connect — content engine", body)


@app.get("/connect/google")
def connect_google():
    if not config.google_ready():
        return layout("Not configured", "<p>Set GOOGLE_CLIENT_ID/SECRET first.</p>"), 400
    state = _secrets.token_urlsafe(16)
    _PENDING[state] = {"platform": "google", "label": request.args["label"]}
    return redirect(google.auth_url(state))


@app.get("/connect/meta")
def connect_meta():
    if not config.meta_ready():
        return layout("Not configured", "<p>Set META_APP_ID/SECRET first.</p>"), 400
    state = _secrets.token_urlsafe(16)
    _PENDING[state] = {"platform": "meta", "label": request.args["label"]}
    return redirect(meta.auth_url(state))


@app.get("/callback/google")
def cb_google():
    pend = _PENDING.pop(request.args.get("state", ""), None)
    if request.args.get("error") or not pend:
        return layout("Failed", f"<p class='bad'>OAuth error: "
                      f"{html.escape(request.args.get('error', 'bad state'))}</p>"), 400
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
    return _save_results_html(f"YouTube connected: {title or suffix}", acct_id, saved, wrote)


@app.get("/callback/meta")
def cb_meta():
    pend = _PENDING.pop(request.args.get("state", ""), None)
    if request.args.get("error") or not pend:
        return layout("Failed", f"<p class='bad'>OAuth error: "
                      f"{html.escape(request.args.get('error_description', 'bad state'))}</p>"), 400
    short = meta.exchange_code(request.args["code"])
    token, _ = meta.long_lived(short)
    igs = meta.discover_ig(token)
    if not igs:
        return layout("No Instagram account", "<p class='bad'>No IG Business account is "
                      "linked to your Pages. Link one to a Facebook Page and retry.</p>"), 400
    if len(igs) == 1:
        return _finish_meta(pend["label"], token, igs[0])
    # Multiple IG accounts — store the token server-side and let the user pick.
    key = _secrets.token_urlsafe(12)
    _RESOLVE[key] = {"label": pend["label"], "token": token, "igs": igs}
    opts = "".join(
        f"<li><a href='/callback/meta/pick?key={key}&i={i}'>@{html.escape(g['username'])} "
        f"<span class='muted'>(page: {html.escape(g['page_name'])})</span></a></li>"
        for i, g in enumerate(igs))
    return layout("Pick an Instagram account", f"<h1>Which account?</h1><ul>{opts}</ul>")


@app.get("/callback/meta/pick")
def cb_meta_pick():
    data = _RESOLVE.pop(request.args.get("key", ""), None)
    if not data:
        return layout("Expired", "<p class='bad'>Selection expired — reconnect.</p>"), 400
    return _finish_meta(data["label"], data["token"], data["igs"][int(request.args["i"])])


def _finish_meta(label: str, token: str, ig: dict):
    suffix = _suffix(label)
    saved = [
        store.save_secret(f"INSTAGRAM_ACCESS_TOKEN_{suffix}", token),
        store.save_secret(f"INSTAGRAM_BUSINESS_ACCOUNT_ID_{suffix}", ig["ig_id"]),
    ]
    wrote, acct_id = accounts.scaffold("instagram", suffix, identity=f"@{ig['username']}")
    return _save_results_html(f"Instagram connected: @{ig['username']}", acct_id, saved, wrote)


if __name__ == "__main__":
    print(f"\n  Connect helper → {config.BASE_URL}\n")
    webbrowser.open(config.BASE_URL)
    app.run(port=config.PORT, debug=False)
