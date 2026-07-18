"""analytics/git_merge_json.py — domain-aware merge for the committed state files.

The posting, analyze and pinterest crons all commit the same JSON files from separate
checkouts. When two runs raced (Jul 13 + Jul 17 2026), `git pull --rebase` hit a
same-line conflict, the `|| true` swallowed it, the push failed — and the ledger row
for a PUBLISHED post was silently lost, starving the learning loop of exactly the
data it runs on. Textual merge can't resolve two appends to one JSON array; this
script can, because it knows what the files mean:

  ledger.json     list of rows   → union by (platform, video_id); the more-measured
                                   row wins (finalized > not, then more keys)
  followers.json  list of rows   → union by (date, account_id); ours wins
  state.json      dict           → deep-merge, lists union (order-preserving), ours
                                   wins on scalar conflicts
  .usage.json     dict name→date → per-key max date
  anything else                  → ours wins (winners/strategy are derived anyway)

Usage (from a workflow persist step, after a failed push):
    git fetch origin main
    python analytics/git_merge_json.py file [file ...]
Each file's working-tree version is rewritten as merge(origin's version, ours);
paths are relative to the repo subdir the step runs in (ninnitales-shorts/).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ORIGIN_REF = "FETCH_HEAD"          # set by the `git fetch origin main` just before us


def _origin_version(path: str):
    """The file's JSON as of origin/main, or None if it doesn't exist there."""
    prefix = subprocess.run(["git", "rev-parse", "--show-prefix"],
                            capture_output=True, text=True).stdout.strip()
    r = subprocess.run(["git", "show", f"{ORIGIN_REF}:{prefix}{path}"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except ValueError:
        return None


def _row_score(row: dict) -> tuple:
    return (bool(row.get("finalized")), len(row))


def _merge_keyed_list(theirs: list, ours: list, key) -> list:
    """Union of rows by key; on collision keep the more-complete row, ours on tie."""
    out: dict = {}
    for row in list(theirs) + list(ours):
        if not isinstance(row, dict):
            continue
        k = key(row)
        if k in out and _row_score(out[k]) > _row_score(row):
            continue
        out[k] = row
    return list(out.values())


def _merge_dict(theirs: dict, ours: dict) -> dict:
    out = dict(theirs)
    for k, v in ours.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _merge_dict(out[k], v)
        elif k in out and isinstance(out[k], list) and isinstance(v, list):
            seen = set()
            merged = []
            for item in out[k] + v:
                mark = json.dumps(item, sort_keys=True) if isinstance(
                    item, (dict, list)) else item
                if mark not in seen:
                    seen.add(mark)
                    merged.append(item)
            out[k] = merged
        else:
            out[k] = v
    return out


def merge(path: str, theirs, ours):
    name = Path(path).name
    if theirs is None or type(theirs) is not type(ours):
        return ours
    if name == "ledger.json":
        rows = _merge_keyed_list(theirs, ours,
                                 key=lambda r: (r.get("platform"), r.get("video_id")))
        rows.sort(key=lambda r: r.get("posted_at") or "")
        return rows
    if name == "followers.json":
        rows = _merge_keyed_list(theirs, ours,
                                 key=lambda r: (r.get("date"), r.get("account_id")))
        rows.sort(key=lambda r: (r.get("date") or "", r.get("account_id") or ""))
        return rows
    if name == ".usage.json":
        return {k: max(theirs.get(k, ""), ours.get(k, ""))
                for k in {*theirs, *ours}}
    if isinstance(ours, dict):
        return _merge_dict(theirs, ours)
    return ours


def main() -> int:
    for path in sys.argv[1:]:
        p = Path(path)
        if not p.exists():
            continue
        try:
            ours = json.loads(p.read_text())
        except ValueError:
            print(f"  ⚠️  {path}: local file isn't valid JSON — leaving as-is")
            continue
        merged = merge(path, _origin_version(path), ours)
        p.write_text(json.dumps(merged, indent=2, ensure_ascii=False))
        print(f"  🔀 merged {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
