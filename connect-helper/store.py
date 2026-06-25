"""store.py — write a secret to BOTH the engine's .env and the GitHub repo secret.

This is the whole point of the helper: a single action keeps the local .env and the
GitHub Actions secret in lockstep, so they can never drift apart (the drift that caused
this project's recurring token-revocation pain). Every connect calls `save_secret()` per
credential; it reports per-target success so the UI can show exactly what landed where.

GitHub writes go through the `gh` CLI (`gh secret set`), so a one-time `gh auth login`
is required; `gh_ready()` lets the app warn up front.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import config


@dataclass
class SaveResult:
    key: str
    env_ok: bool
    gh_ok: bool
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.env_ok and self.gh_ok


# ── local .env ──────────────────────────────────────────────────────────────────
def upsert_env(key: str, value: str, path: Path | None = None) -> bool:
    """Replace the `KEY=` line in .env, or append it. Leaves every other line intact."""
    path = path or config.TARGET_ENV
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text().splitlines() if path.exists() else []
    pat = re.compile(rf"^\s*{re.escape(key)}\s*=")
    out, replaced = [], False
    for line in lines:
        if pat.match(line):
            out.append(f"{key}={value}")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.append(f"{key}={value}")
    path.write_text("\n".join(out) + "\n")
    return True


# ── GitHub repo secrets ───────────────────────────────────────────────────────
def gh_ready() -> bool:
    """True if the gh CLI is installed AND authenticated."""
    if not shutil.which("gh"):
        return False
    r = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
    return r.returncode == 0


def detect_repo() -> str | None:
    """owner/name from the git origin remote (e.g. codeReadyy/Content-Creation)."""
    r = subprocess.run(["git", "remote", "get-url", "origin"],
                       capture_output=True, text=True, cwd=config.REPO_ROOT)
    if r.returncode != 0:
        return None
    url = r.stdout.strip()
    m = re.search(r"github\.com[:/](?P<owner>[^/]+)/(?P<name>[^/]+?)(?:\.git)?/?$", url)
    return f"{m['owner']}/{m['name']}" if m else None


def set_github_secret(key: str, value: str) -> tuple[bool, str]:
    repo = detect_repo()
    if not repo:
        return False, "could not detect GitHub repo from origin remote"
    r = subprocess.run(
        ["gh", "secret", "set", key, "--repo", repo, "--body", value],
        capture_output=True, text=True)
    if r.returncode != 0:
        return False, (r.stderr or r.stdout).strip()
    return True, repo


# ── both at once ──────────────────────────────────────────────────────────────
def save_secret(key: str, value: str, to_github: bool = True) -> SaveResult:
    """Write a credential to .env and (optionally) the GitHub repo secret."""
    env_ok = upsert_env(key, value)
    if not to_github:
        return SaveResult(key, env_ok, gh_ok=True, detail="env only")
    gh_ok, detail = set_github_secret(key, value)
    return SaveResult(key, env_ok, gh_ok, detail)
