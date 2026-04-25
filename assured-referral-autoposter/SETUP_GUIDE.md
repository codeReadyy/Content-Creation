# AssuredReferral AutoPoster — Setup Guide

## How It Works

Every day at 10:00 AM IST, GitHub Actions automatically:
1. Generates carousel content using Azure OpenAI (GPT-4o)
2. Creates 5 slide images with AI backgrounds (DALL-E 3)
3. Posts the carousel to your LinkedIn (personal + company page)
4. Uploads a Short to YouTube
5. Saves all outputs as downloadable artifacts

You don't need to keep any machine running — GitHub does it for free.

---

## Step 1: Push This Repo to GitHub

```bash
cd assured-referral-autoposter
git init
git add .
git commit -m "Initial commit: AutoPoster pipeline"
git remote add origin https://github.com/YOUR_USERNAME/assured-referral-autoposter.git
git push -u origin main
```

Use a **private repo** to keep your workflow secure.

---

## Step 2: Add GitHub Secrets

Go to your repo: **Settings → Secrets and variables → Actions → New repository secret**

Add each of these:

### Azure OpenAI (Required)

| Secret Name | Where to Find It |
|---|---|
| `AZURE_OPENAI_API_KEY` | Azure Portal → Your OpenAI resource → Keys and Endpoint |
| `AZURE_OPENAI_ENDPOINT` | Same page — looks like `https://your-resource.openai.azure.com/` |
| `AZURE_OPENAI_API_VERSION` | Use `2024-10-21` (or latest from Azure docs) |
| `AZURE_OPENAI_CHAT_DEPLOYMENT` | Azure OpenAI Studio → Deployments → your GPT-4o deployment name |
| `AZURE_OPENAI_DALLE_DEPLOYMENT` | Azure OpenAI Studio → Deployments → your DALL-E 3 deployment name |
| `IMAGE_PROVIDER` | Set to `azure` (or `gradient` to skip AI images and save cost) |

### LinkedIn

| Secret Name | How to Get It |
|---|---|
| `LINKEDIN_ACCESS_TOKEN` | Run `python publishers/linkedin.py` locally (one-time setup) |
| `LINKEDIN_PERSON_URN` | `curl -H "Authorization: Bearer TOKEN" https://api.linkedin.com/v2/userinfo` → use the `sub` field as `urn:li:person:SUB_VALUE` |
| `LINKEDIN_ORG_ID` | Your company page URL: `linkedin.com/company/THIS_NUMBER/` |

**LinkedIn App Setup:**
1. Go to [linkedin.com/developers/apps](https://www.linkedin.com/developers/apps)
2. Create app → request "Share on LinkedIn" product
3. Auth tab → add `http://localhost:8080/callback` as redirect URL
4. Run `python publishers/linkedin.py` to get your access token

**Token refresh:** LinkedIn tokens expire in 60 days. Set a calendar reminder to re-run the auth helper and update the GitHub secret.

### YouTube

| Secret Name | How to Get It |
|---|---|
| `YOUTUBE_CLIENT_ID` | Google Cloud Console → APIs & Services → Credentials |
| `YOUTUBE_CLIENT_SECRET` | Same page |
| `YOUTUBE_REFRESH_TOKEN` | Run `python publishers/youtube.py` locally (one-time setup) |
| `YOUTUBE_CHANNEL_ID` | YouTube Studio → Settings → Channel → Advanced → Channel ID |

**Google Cloud Setup:**
1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create project → enable "YouTube Data API v3"
3. Create OAuth 2.0 credentials (Desktop app type)
4. Run `python publishers/youtube.py` to get your refresh token

---

## Step 3: Enable the Workflow

1. Go to your repo → **Actions** tab
2. You should see "Daily AutoPost" workflow
3. Click **Enable workflow** if prompted
4. Click **Run workflow** to test it manually first

---

## Step 4: Verify It Works

After a manual run:
1. Check the Actions tab for green/red status
2. Click the run → download the "daily-output" artifact to see generated slides
3. Check your LinkedIn and YouTube for the post

---

## Local Development

To test locally without publishing:

```bash
pip install -r requirements.txt
cp .env.example .env
# Fill in .env with your credentials

python main.py --dry-run              # Generate content only
python main.py --dry-run --no-ai-images  # Fastest test (no API calls for images)
python main.py                        # Full pipeline with publishing
```

---

## Cost Estimate

Per daily run with Azure OpenAI:
- GPT-4o content generation: ~$0.03-0.05
- DALL-E 3 (5 images): ~$0.20-0.40
- **Total: ~$0.25-0.45/day (~$8-14/month)**

To reduce cost, set `IMAGE_PROVIDER=gradient` in secrets — this uses free local gradient backgrounds instead of AI images.

---

## Content Themes

The system rotates through 14 themes, one per day:
job search tips, referral power, recruiter insights, career growth, interview prep, networking, resume/profile, hiring trends, referrer benefits, success stories, AI in hiring, salary negotiation, company culture, and side hustles.

Every post ends with a soft AssuredReferral CTA and branding.

---

## Folder Structure

```
assured-referral-autoposter/
├── main.py                    # Pipeline orchestrator (entry point)
├── scheduler.py               # Optional: local scheduler alternative
├── requirements.txt
├── .env.example               # Config template
├── .gitignore
├── SETUP_GUIDE.md             # This file
├── config/
│   └── settings.py            # Configuration loader
├── content/
│   └── generator.py           # Azure OpenAI content generation
├── slides/
│   ├── image_gen.py           # Azure DALL-E 3 / Stability / gradient
│   └── builder.py             # Slide compositor + video creator
├── publishers/
│   ├── linkedin.py            # LinkedIn API + OAuth helper
│   ├── youtube.py             # YouTube API + OAuth helper
│   └── instagram.py           # Instagram placeholder
├── output/                    # Daily outputs (git-ignored)
└── .github/workflows/
    └── daily-post.yml         # GitHub Actions daily scheduler
```

---

## Troubleshooting

**Pipeline fails on Azure OpenAI call:** Check that your deployment names in secrets match exactly what's in Azure OpenAI Studio. Also verify the API version is correct.

**LinkedIn 403 error:** Access token expired (60-day limit). Re-run `python publishers/linkedin.py` locally and update the `LINKEDIN_ACCESS_TOKEN` secret.

**YouTube upload fails:** Ensure YouTube Data API v3 is enabled in Google Cloud Console. Check that the refresh token hasn't been revoked.

**Slides have bad fonts:** The workflow installs `fonts-dejavu` automatically. If running locally, install it: `sudo apt install fonts-dejavu` (Linux) or use the bundled system fonts (macOS).

**Want to skip a day:** Just disable the workflow temporarily in GitHub Actions settings.
