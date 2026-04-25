# AssuredReferral AutoPoster — Claude Code Briefing

## Project

Monorepo: `Content-Creation-Flows`
Active project folder: `assured-referral-autoposter/`
GitHub Actions at repo root: `.github/workflows/`

## What's Already Built

- `content/generator.py` — Azure OpenAI GPT-4o carousel content generator, 14 rotating themes
- `slides/builder.py` + `slides/image_gen.py` — 1080x1080 carousel images + MP4 for YouTube Shorts
- `publishers/linkedin.py` — posts to personal profile + company page via 3-legged OAuth
- `publishers/youtube.py` — uploads Shorts via YouTube Data API v3
- `publishers/instagram.py` — placeholder only
- `main.py` — orchestrator: generate → build → video → publish
- `config/settings.py` — reads all config from env vars / .env

## What Needs to Be Built (Research Layer)

### Goal

Before generating content, the pipeline must RESEARCH what's trending that day
and produce a structured content brief that drives carousel generation.

### New folder to create: `research/`

```
research/
  __init__.py
  trending.py          ← orchestrates all sources
  synthesizer.py       ← GPT-4o turns signals into content brief
  sources/
    __init__.py
    google_trends.py   ← pytrends, job/hiring keywords
    reddit_scraper.py  ← hot posts from r/jobs, r/cscareerquestions,
                          r/recruitinghell, r/jobsearchhacks
    web_search.py      ← Tavily API for real-time web search
```

### New secrets needed

- `TAVILY_API_KEY` — tavily.com, free tier 1000/month
- `REDDIT_CLIENT_ID` + `REDDIT_CLIENT_SECRET` — reddit.com/prefs/apps

### Pipeline order (updated main.py)

1. `gather_all_signals()` — pulls Google Trends + Reddit + Tavily
2. `synthesize_brief()` — GPT-4o reads signals → returns structured JSON brief
3. `generate_from_brief(brief)` — carousel generator uses brief (hook, angle, keywords)
4. Build slides → publish (existing, unchanged)

### Content Brief Schema (what synthesizer.py must return)

```json
{
  "trending_angle": "specific trending topic to build around",
  "hook_headline": "slide 1 opener, <10 words, bold claim or stat",
  "hook_type": "stat | question | controversy | story | list",
  "keywords_to_use": ["keyword1", "keyword2"],
  "hashtags": ["#hashtag1", "#hashtag2"],
  "tone": "inspirational | controversial | data-driven | storytelling",
  "carousel_angle": "specific angle for today's carousel",
  "why_this_works_today": "why this is timely"
}
```

### Hook Integration

- File: `hooks/viral_hooks.txt` (1000 proven viral hooks)
- The synthesizer must SELECT the best matching hook from this file
  based on today's trending angle — do NOT generate hooks from scratch
- Match by: hook_type + emotional tone + topic relevance

### Updated generator.py behavior

- Accept a `brief` dict as input
- Use `brief['hook_headline']` as Slide 1 EXACTLY
- Weave in `brief['keywords_to_use']` naturally
- Match `brief['tone']` throughout

## About AssuredReferral (product context for all prompts)

- Free tool: job seekers get warm referrals at dream companies
- Recruiters: AI screens 10,000+ CVs for high-intent candidates
- Referrers: earn bonuses for successful referrals
- AI interviews + profile screening built in
- Tagline: "Get Referred. Get Hired. Get Rewarded."
- Website: assuredreferral.com
- Soft CTA on every last slide

## Content Style

- Bold, TikTok/Instagram carousel visual style
- Business/startup niche, inspirational tone
- AI-generated image backgrounds
- Every post ends with soft CTA for AssuredReferral

## Existing Secrets (already in GitHub)

AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_VERSION,
AZURE_OPENAI_CHAT_DEPLOYMENT, AZURE_OPENAI_IMAGE_DEPLOYMENT, IMAGE_PROVIDER,
LINKEDIN_ACCESS_TOKEN, LINKEDIN_PERSON_URN, LINKEDIN_ORG_ID,
YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN, YOUTUBE_CHANNEL_ID
