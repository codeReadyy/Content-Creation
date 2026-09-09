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

ASSET CAP: a GitHub release holds at most 1000 assets — past that EVERY upload returns
`422 Unprocessable Entity` and publishing dies silently (Sep 3 2026: the ninnitales
release filled up and every Pinterest pin + IG post failed on hosting). The release is a
rolling buffer, not an archive: media only has to stay reachable until the platform
ingests it (Instagram fetches within seconds; Pinterest's RSS auto-publish within 24-48h,
and the feeds themselves keep just 50 items/board). So we PRUNE before uploading — drop
assets older than MEDIA_RETENTION_DAYS (default 45), then, if still tight, the oldest
ones — keeping headroom under the cap.

Locally (no token/repo env) public_url() raises — which is why the Instagram account
stays effectively inert until run in CI with creds.
"""

from __future__ import annotations

import mimetypes
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

API = "https://api.github.com"

ASSET_CAP = 1000        # GitHub's hard limit of assets per release
SOFT_CAP = 940          # prune once we're this close, so uploads never hit the wall
RETENTION_DAYS = int(os.environ.get("MEDIA_RETENTION_DAYS", "45"))


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


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}


def _ensure_release(repo: str, token: str) -> dict:
    tag = _project()
    h = _headers(token)
    r = requests.get(f"{API}/repos/{repo}/releases/tags/{tag}", headers=h, timeout=30)
    if r.status_code == 200:
        return r.json()
    r = requests.post(f"{API}/repos/{repo}/releases", headers=h, timeout=30, json={
        "tag_name": tag, "name": f"Media — {tag}", "prerelease": True,
        "body": f"Auto-hosted media for '{tag}' (Instagram publishing; safe to prune old assets).",
    })
    r.raise_for_status()
    return r.json()


def _list_assets(repo: str, token: str, release_id: int) -> list[dict]:
    """Every asset on the release (the embedded list can be paginated away)."""
    out: list[dict] = []
    for page in range(1, 12):          # 11 pages × 100 > the 1000 cap
        r = requests.get(f"{API}/repos/{repo}/releases/{release_id}/assets",
                         headers=_headers(token),
                         params={"per_page": 100, "page": page}, timeout=30)
        r.raise_for_status()
        batch = r.json()
        out += batch
        if len(batch) < 100:
            break
    return out


def _age_key(asset: dict) -> float:
    """Epoch seconds for an asset's creation time (unparseable → treat as ancient)."""
    try:
        return datetime.strptime(asset["created_at"], "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc).timestamp()
    except (KeyError, ValueError):
        return 0.0


def _delete_asset(repo: str, token: str, asset_id: int) -> bool:
    r = requests.delete(f"{API}/repos/{repo}/releases/assets/{asset_id}",
                        headers=_headers(token), timeout=30)
    return r.status_code in (204, 404)   # 404 = someone else already pruned it


def _prune(repo: str, token: str, release_id: int, target: int = SOFT_CAP) -> int:
    """Free space on the release so the next upload can't 422. Returns assets deleted.

    Oldest-first: everything past MEDIA_RETENTION_DAYS goes, then — only if that wasn't
    enough — the oldest survivors, until the release is under `target`.
    """
    assets = sorted(_list_assets(repo, token, release_id), key=_age_key)
    if len(assets) < target:
        return 0
    cutoff = time.time() - RETENTION_DAYS * 86400
    deleted = 0
    remaining = len(assets)
    for a in assets:
        expired = _age_key(a) < cutoff
        if not expired and remaining < target:
            break                       # in-retention and we already have headroom
        if _delete_asset(repo, token, a["id"]):
            deleted += 1
            remaining -= 1
    print(f"  🧹 hosting: pruned {deleted} old asset(s) from release "
          f"'{_project()}' ({remaining} left of {ASSET_CAP})")
    return deleted


def _upload(repo: str, token: str, rel: dict, path: Path, name: str, ctype: str):
    upload = rel["upload_url"].split("{")[0]
    with open(path, "rb") as f:
        return requests.post(f"{upload}?name={name}",
                             headers={"Authorization": f"Bearer {token}",
                                      "Content-Type": ctype},
                             data=f, timeout=300)


def public_url(path: str | Path) -> str:
    """Upload `path` as a release asset and return its public browser_download_url."""
    path = Path(path)
    repo, token = _repo_token()
    rel = _ensure_release(repo, token)
    name = f"{int(time.time())}_{path.name}"
    ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"

    # Keep the rolling buffer under GitHub's 1000-asset cap before we add to it.
    if len(rel.get("assets", [])) >= SOFT_CAP:
        _prune(repo, token, rel["id"])

    r = _upload(repo, token, rel, path, name, ctype)
    if r.status_code == 422:
        # Full (or a name collision) despite the check. Force a prune with real headroom
        # — never a scorched-earth one: assets younger than the retention window are
        # still being fetched by Pinterest's feed ingest.
        _prune(repo, token, rel["id"], target=SOFT_CAP - 60)
        name = f"{int(time.time())}_{os.getpid()}_{path.name}"
        r = _upload(repo, token, rel, path, name, ctype)
    r.raise_for_status()
    return r.json()["browser_download_url"]
