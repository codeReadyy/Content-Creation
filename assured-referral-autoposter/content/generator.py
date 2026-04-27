"""
Content generation engine for AssuredReferral daily posts.
Uses Azure OpenAI GPT to generate carousel slide content with a soft product CTA.
"""

import json
import random
from datetime import date
from openai import AzureOpenAI
from config.settings import Config

# Rotating content themes — one per day, cycles through
CONTENT_THEMES = [
    {
        "theme": "job_search_tips",
        "angle": "Unconventional job search strategies that actually work",
        "hook_style": "myth-busting"
    },
    {
        "theme": "referral_power",
        "angle": "Why referrals are 10x more effective than cold applications",
        "hook_style": "statistic-driven"
    },
    {
        "theme": "recruiter_insights",
        "angle": "What recruiters actually look for (insider perspective)",
        "hook_style": "behind-the-scenes"
    },
    {
        "theme": "career_growth",
        "angle": "Career moves that compound over time",
        "hook_style": "story-driven"
    },
    {
        "theme": "interview_prep",
        "angle": "Interview hacks from people who've cracked FAANG",
        "hook_style": "listicle"
    },
    {
        "theme": "networking",
        "angle": "How to build genuine professional connections (not just connections)",
        "hook_style": "contrarian"
    },
    {
        "theme": "resume_profile",
        "angle": "Profile and resume mistakes costing you interviews",
        "hook_style": "problem-solution"
    },
    {
        "theme": "hiring_trends",
        "angle": "What's changing in hiring and how to stay ahead",
        "hook_style": "trend-analysis"
    },
    {
        "theme": "referrer_benefits",
        "angle": "Why smart professionals refer candidates (it's not just the bonus)",
        "hook_style": "perspective-shift"
    },
    {
        "theme": "success_stories",
        "angle": "From rejected everywhere to dream job — what changed",
        "hook_style": "transformation"
    },
    {
        "theme": "ai_in_hiring",
        "angle": "How AI is reshaping recruitment (and how to use it to your advantage)",
        "hook_style": "future-forward"
    },
    {
        "theme": "salary_negotiation",
        "angle": "Negotiation frameworks that got people 30-50% higher offers",
        "hook_style": "tactical"
    },
    {
        "theme": "company_culture",
        "angle": "How to evaluate company culture before you accept the offer",
        "hook_style": "checklist"
    },
    {
        "theme": "side_hustle_to_career",
        "angle": "Turning side projects into career opportunities",
        "hook_style": "inspirational"
    },
]


def get_todays_theme() -> dict:
    """Pick today's theme based on day-of-year rotation."""
    day_index = date.today().timetuple().tm_yday % len(CONTENT_THEMES)
    return CONTENT_THEMES[day_index]


SYSTEM_PROMPT = """You are a viral content creator for LinkedIn and Instagram carousels.
You create content for AssuredReferral — a free tool that:
- Helps job seekers connect directly with professionals and get referrals at their dream companies
- Gives recruiters AI-powered screening that processes 10,000+ CVs instantly to find high-intent, interview-ready candidates
- Rewards referrers with bonuses by matching them with candidates most likely to crack interviews
- Uses AI to screen profiles and set up AI interviews

Brand: AssuredReferral
Tagline: "Get Referred. Get Hired. Get Rewarded."
Website: assuredreferral.com

RULES:
1. Generate EXACTLY the number of slides requested (between 3 and 6)
2. Slide 1 is ALWAYS a bold, scroll-stopping hook (question, bold claim, or surprising stat)
3. Middle slides deliver genuine value — tips, insights, frameworks, stories
4. Last slide is ALWAYS a soft CTA that ties the content back to AssuredReferral naturally
   - Never be salesy. Frame it as "here's a tool that does this" or "this is why we built AssuredReferral"
   - Always include: "assuredreferral.com" and the tagline
5. Tone: Inspirational, bold, punchy. Short sentences. Use line breaks for impact.
6. Each slide should have 20-40 words MAX
7. DO NOT use any emojis or special characters. Use plain text only.

OUTPUT FORMAT (strict JSON):
{
  "slides": [
    {"slide_number": 1, "text": "...", "image_prompt": "..."},
    ...
  ],
  "caption": "LinkedIn/Instagram caption text with hashtags",
  "hashtags": ["#tag1", "#tag2", ...],
  "youtube_title": "Short catchy title for YouTube Short",
  "youtube_description": "Brief description with link"
}

For image_prompt: describe a clean, modern, professional background image.
Think: abstract gradients, minimalist office scenes, tech-inspired patterns.
NO text in the image. NO people's faces. Just atmospheric backgrounds.
"""


def generate_content(num_slides: int = 5, brief: dict = None) -> dict:
    """
    Generate carousel content for today's theme or from a research brief.
    Returns structured content with slide text, image prompts, and captions.

    Args:
        num_slides: Number of slides to generate (3-6)
        brief: Optional content brief from research.synthesizer.synthesize_brief()
               If provided, uses brief's hook, keywords, and tone.
    """
    num_slides = max(3, min(6, num_slides))

    client = AzureOpenAI(
        api_key=Config.AZURE_OPENAI_API_KEY,
        azure_endpoint=Config.AZURE_OPENAI_ENDPOINT,
        api_version=Config.AZURE_OPENAI_API_VERSION,
    )

    # Build prompt based on whether we have a research brief
    if brief:
        user_prompt = _build_brief_prompt(num_slides, brief)
        system_content = _get_brief_system_prompt()
    else:
        # Fallback to original theme-based generation
        theme = get_todays_theme()
        user_prompt = f"""Create a {num_slides}-slide carousel post about:
Theme: {theme['theme']}
Angle: {theme['angle']}
Hook style: {theme['hook_style']}
Today's date: {date.today().isoformat()}

Remember:
- Slide 1 = scroll-stopping hook
- Slides 2 to {num_slides - 1} = pure value
- Slide {num_slides} = soft AssuredReferral CTA with website link
- Keep each slide to 20-40 words
- Make it feel like advice from a mentor, not an ad
"""
        system_content = SYSTEM_PROMPT

    response = client.chat.completions.create(
        model=Config.AZURE_OPENAI_CHAT_DEPLOYMENT,
        messages=[
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_prompt}
        ],
        response_format={"type": "json_object"},
        temperature=0.85,
        max_tokens=1500
    )

    content = json.loads(response.choices[0].message.content)

    # Validate structure
    assert "slides" in content, "Missing 'slides' in response"
    assert len(content["slides"]) == num_slides, f"Expected {num_slides} slides, got {len(content['slides'])}"

    # If brief provided, override hashtags with brief's hashtags
    if brief and brief.get("hashtags"):
        content["hashtags"] = brief["hashtags"]

    return content


def _get_brief_system_prompt() -> str:
    """System prompt for brief-driven content generation."""
    return """You are a viral content creator for LinkedIn and Instagram carousels.
You create content for AssuredReferral — a free tool that:
- Helps job seekers connect directly with professionals and get referrals at their dream companies
- Gives recruiters AI-powered screening that processes 10,000+ CVs instantly to find high-intent, interview-ready candidates
- Rewards referrers with bonuses by matching them with candidates most likely to crack interviews
- Uses AI to screen profiles and set up AI interviews

Brand: AssuredReferral
Tagline: "Get Referred. Get Hired. Get Rewarded."
Website: assuredreferral.com

RULES:
1. Generate EXACTLY the number of slides requested (between 3 and 6)
2. Slide 1 MUST use the EXACT hook_headline provided — do NOT modify it
3. Middle slides deliver genuine value aligned with the carousel_angle
4. Naturally incorporate the keywords_to_use in the content
5. Match the specified tone throughout all slides
6. Last slide is ALWAYS a soft CTA that ties content back to AssuredReferral naturally
   - Never be salesy. Frame it as "here's a tool that does this" or "this is why we built AssuredReferral"
   - Always include: "assuredreferral.com" and the tagline
7. Tone: Match the specified tone. Short sentences. Use line breaks for impact.
8. Each slide should have 20-40 words MAX
9. DO NOT use any emojis or special characters. Use plain text only.

OUTPUT FORMAT (strict JSON):
{
  "slides": [
    {"slide_number": 1, "text": "...", "image_prompt": "..."},
    ...
  ],
  "caption": "LinkedIn/Instagram caption text",
  "hashtags": ["#tag1", "#tag2", ...],
  "youtube_title": "Short catchy title for YouTube Short",
  "youtube_description": "Brief description with link"
}

For image_prompt: describe a clean, modern, professional background image.
Think: abstract gradients, minimalist office scenes, tech-inspired patterns.
NO text in the image. NO people's faces. Just atmospheric backgrounds.
"""


def _build_brief_prompt(num_slides: int, brief: dict) -> str:
    """Build the user prompt from a research brief."""
    keywords = ", ".join(brief.get("keywords_to_use", []))
    hashtags = " ".join(brief.get("hashtags", []))

    return f"""Create a {num_slides}-slide carousel post based on this research brief:

TRENDING ANGLE: {brief.get('trending_angle', 'Career growth strategies')}

HOOK HEADLINE (use EXACTLY on Slide 1): {brief.get('hook_headline', 'Your job search strategy needs an upgrade.')}

HOOK TYPE: {brief.get('hook_type', 'question')}

CAROUSEL ANGLE: {brief.get('carousel_angle', 'Job search strategies')}

TONE: {brief.get('tone', 'inspirational')}

KEYWORDS TO WEAVE IN: {keywords}

WHY THIS WORKS TODAY: {brief.get('why_this_works_today', 'Timely and relevant')}

Today's date: {date.today().isoformat()}

CRITICAL INSTRUCTIONS:
- Slide 1 MUST be the EXACT hook_headline provided above (you can add emoji)
- Slides 2 to {num_slides - 1} = pure value content matching the carousel_angle
- Slide {num_slides} = soft AssuredReferral CTA with website link
- Naturally use the keywords in the content
- Match the {brief.get('tone', 'inspirational')} tone throughout
- Keep each slide to 20-40 words
- Make it feel like advice from a mentor, not an ad
"""


def generate_content_batch(days: int = 7, slides_per_post: int = 5) -> list[dict]:
    """Generate content for multiple days at once (for buffering)."""
    results = []
    for i in range(days):
        content = generate_content(num_slides=slides_per_post)
        results.append(content)
    return results


if __name__ == "__main__":
    # Test run
    theme = get_todays_theme()
    print(f"Today's theme: {theme['theme']}")
    print(f"Angle: {theme['angle']}")
    print(f"Hook style: {theme['hook_style']}")
    print()

    # Uncomment to test with real API key:
    # content = generate_content(5)
    # print(json.dumps(content, indent=2))
