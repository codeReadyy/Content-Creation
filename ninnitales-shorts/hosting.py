"""hosting.py — expose a built local asset at a public HTTPS URL.

Instagram's Graph API ingests media BY URL (it fetches the file itself), not by upload,
so a freshly built mp4/image must be reachable over the web. We attach it as an asset on
a single rolling GitHub Release, which gives a durable public download URL.

This repo can stay PRIVATE: point hosting at a SEPARATE PUBLIC "media" repo via
  MEDIA_REPO        = "owner/posted-media"  (one public repo, shared across projects)
  MEDIA_REPO_TOKEN  = a PAT with `repo` scope on it (or `contents:write` fine-grained)
  MEDIA_PREFIX      = "ninnitales"          (the project bucket; default "ninnitales")
Only the built clips land there — never your code or secrets. If MEDIA_REPO is unset we
fall back to the current repo (GITHUB_REPOSITORY + GITHUB_TOKEN), which only yields a
public URL when THIS repo is public.

PER-PROJECT GROUPING: each project gets its OWN release inside the shared media repo,
tagged with MEDIA_PREFIX (so `posted-media` holds a `ninnitales` release now, and a new
release per future project). We use Releases rather than committed files because GitHub's
Contents API caps ~1 MB while videos are larger; release assets handle big media + give a
durable public download URL.

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


def _project() -> str:
    """The per-project bucket = the release tag inside the shared media repo."""
    return os.environ.get("MEDIA_PREFIX", "ninnitales")


def _repo_token() -> tuple[str, str]:
    # Prefer a dedicated public media repo so this repo can stay private.
    repo = os.environ.get("MEDIA_REPO") or os.environ.get("GITHUB_REPOSITORY")
    token = (os.environ.get("MEDIA_REPO_TOKEN") or os.environ.get("GH_PAT")
             or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN"))
    if not token or not repo:
        raise RuntimeError(
            "hosting needs a repo + token to host media for Instagram — set MEDIA_REPO + "
            "MEDIA_REPO_TOKEN (a public media repo), or run in Actions with GITHUB_REPOSITORY "
            "+ GITHUB_TOKEN on a public repo.")
    return repo, token


def _ensure_release(repo: str, token: str) -> dict:
    tag = _project()
    h = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    r = requests.get(f"{API}/repos/{repo}/releases/tags/{tag}", headers=h, timeout=30)
    if r.status_code == 200:
        return r.json()
    r = requests.post(f"{API}/repos/{repo}/releases", headers=h, timeout=30, json={
        "tag_name": tag, "name": f"Media — {tag}", "prerelease": True,
        "body": f"Auto-hosted media for '{tag}' (Instagram publishing; safe to prune old assets).",
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
