"""hosting.py — expose a built local asset at a public HTTPS URL.

Instagram's Graph API ingests media BY URL (it fetches the file itself), not by upload,
so a freshly built mp4/image must be reachable over the web. We attach it as an asset on
a single rolling GitHub Release (free, durable, public on a public repo), using the
GITHUB_TOKEN + GITHUB_REPOSITORY that GitHub Actions injects automatically.

Locally (no token/repo env) public_url() raises — which is why the Instagram account
stays effectively inert until run in CI with creds.
"""

from __future__ import annotations

import mimetypes
import os
import time
from pathlib import Path

import requests

API = "https://api.github.com"
RELEASE_TAG = "media-assets"   # one rolling pre-release that holds posted media


def _repo_token() -> tuple[str, str]:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")          # "owner/name" (set by Actions)
    if not token or not repo:
        raise RuntimeError("hosting needs GITHUB_TOKEN + GITHUB_REPOSITORY "
                           "(present in GitHub Actions) to host media for Instagram.")
    return repo, token


def _ensure_release(repo: str, token: str) -> dict:
    h = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    r = requests.get(f"{API}/repos/{repo}/releases/tags/{RELEASE_TAG}", headers=h, timeout=30)
    if r.status_code == 200:
        return r.json()
    r = requests.post(f"{API}/repos/{repo}/releases", headers=h, timeout=30, json={
        "tag_name": RELEASE_TAG, "name": "Media assets", "prerelease": True,
        "body": "Auto-hosted media for Instagram publishing (safe to prune old assets).",
    })
    r.raise_for_status()
    return r.json()


def public_url(path: str | Path) -> str:
    """Upload `path` as a release asset and return its public browser_download_url."""
    path = Path(path)
    repo, token = _repo_token()
    rel = _ensure_release(repo, token)
    name = f"{int(time.time())}_{path.name}"
    ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    upload = rel["upload_url"].split("{")[0]
    with open(path, "rb") as f:
        r = requests.post(f"{upload}?name={name}",
                          headers={"Authorization": f"Bearer {token}", "Content-Type": ctype},
                          data=f, timeout=300)
    r.raise_for_status()
    return r.json()["browser_download_url"]
