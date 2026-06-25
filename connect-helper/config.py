"""config.py — settings + provider credentials for the connect-helper.

This app is DECOUPLED from the content engine: it never imports ninnitales-shorts
code. It only writes side effects the engine already consumes — the engine's `.env`,
GitHub repo secrets, and config/accounts.yml. All paths/creds resolve here so the rest
of the app stays logic-only.

Its own settings live in connect-helper/.env (see .env.example). Provider client creds:
  GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET   (reuse the existing NinniTales OAuth client)
  META_APP_ID / META_APP_SECRET             (a Meta app with Facebook Login)
For Google we also fall back to the engine's .env (YOUTUBE_CLIENT_ID_NINNITALES etc.)
so you don't have to re-enter the client you already have.
"""

from __future__ import annotations

import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
ENGINE_DIR = REPO_ROOT / "ninnitales-shorts"


def _load_env_file(path: Path) -> None:
    """Minimal .env loader (KEY=VALUE, # comments) — no python-dotenv dependency."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())


# Load our own .env, then the engine's, then AssuredReferral's — so the existing Google
# OAuth client (stored un-suffixed in assured-referral-autoposter/.env) is reused with no
# re-entry. Mirrors ninnitales-shorts/get_youtube_token.py's loader order.
_load_env_file(HERE / ".env")
_load_env_file(ENGINE_DIR / ".env")
_load_env_file(REPO_ROOT / "assured-referral-autoposter" / ".env")

# ── Server ────────────────────────────────────────────────────────────────────
PORT = int(os.environ.get("CONNECT_PORT", "8765"))
BASE_URL = f"http://localhost:{PORT}"
GOOGLE_REDIRECT = f"{BASE_URL}/callback/google"
META_REDIRECT = f"{BASE_URL}/callback/meta"

# ── Targets the helper writes (the only coupling to the engine, by file) ────────
TARGET_ENV = Path(os.environ.get("TARGET_ENV", ENGINE_DIR / ".env"))
TARGET_ACCOUNTS_YML = Path(
    os.environ.get("TARGET_ACCOUNTS_YML", ENGINE_DIR / "config" / "accounts.yml"))

# Defaults for the scaffolded accounts.yml block (user edits these afterwards).
DEFAULT_PRODUCT = os.environ.get("DEFAULT_PRODUCT", "ninnitales")
DEFAULT_NICHE = os.environ.get("DEFAULT_NICHE", "toddler_sleep")

# ── Provider credentials ────────────────────────────────────────────────────────
GOOGLE_CLIENT_ID = (os.environ.get("GOOGLE_CLIENT_ID")
                    or os.environ.get("YOUTUBE_CLIENT_ID_NINNITALES")
                    or os.environ.get("YOUTUBE_CLIENT_ID"))
GOOGLE_CLIENT_SECRET = (os.environ.get("GOOGLE_CLIENT_SECRET")
                        or os.environ.get("YOUTUBE_CLIENT_SECRET_NINNITALES")
                        or os.environ.get("YOUTUBE_CLIENT_SECRET"))
META_APP_ID = os.environ.get("META_APP_ID")
META_APP_SECRET = os.environ.get("META_APP_SECRET")

# ── OAuth scopes ──────────────────────────────────────────────────────────────
# Google: force-ssl = full manage (upload + schedule + delete, needed for the Telegram
# veto), supersets upload/readonly; + analytics for analyze.py. One token does it all.
GOOGLE_SCOPES = (
    "https://www.googleapis.com/auth/youtube.force-ssl "
    "https://www.googleapis.com/auth/yt-analytics.readonly"
)
# Meta: read pages, find the linked IG business account, and publish to it.
META_SCOPES = ",".join([
    "instagram_basic",
    "instagram_content_publish",
    "pages_show_list",
    "pages_read_engagement",
    "business_management",
])

GRAPH = "https://graph.facebook.com/v21.0"


def google_ready() -> bool:
    return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)


def meta_ready() -> bool:
    return bool(META_APP_ID and META_APP_SECRET)
