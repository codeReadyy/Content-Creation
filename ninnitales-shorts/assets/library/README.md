# Cover photo library

Drop your REAL photos here (home scenes, bedtime corners, play mess, food, travel…)
and list them in `manifest.json`. The carousel picker matches a photo to the day's
topic by tags and won't reuse one within 30 days (tracked in `.usage.json`).

**House rule (human-enforced, not code): kids must never be identifiable** — back of
the head, hands, feet, silhouettes are fine; faces are not. Only add photos you're
comfortable publishing on the public @ninni_tales_ account.

`manifest.json` format (a JSON list):

```json
[
  {"file": "IMG_001.jpg", "tags": ["sleep", "bedtime", "crib", "mess"], "age": "1-3",
   "note": "crib corner at dusk"},
  {"file": "IMG_002.jpg", "tags": ["play", "games", "toys"], "age": "1-7"}
]
```

- `file` — the image filename in this folder (jpg/png).
- `tags` — lowercase topic words; matched against the theme key + its search phrase
  (e.g. theme `picky_eating` / "foods and tricks for picky eater toddlers" matches
  tags like `food`, `eating`, `kitchen`, `mealtime`).
- `age` (optional) — `1-3`, `3-7`, or `1-7`; a match with the day's theme age band
  boosts the photo's score.
- `note` (optional) — for you, ignored by the code.

Portrait/landscape both work (center-cropped to 1080×1350). No matching photo →
the carousel just uses the flat dark cover, so an empty library never blocks a post.
