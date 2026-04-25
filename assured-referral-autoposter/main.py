#!/usr/bin/env python3
"""
AssuredReferral AutoPoster — Main Pipeline Orchestrator
=======================================================
Runs the full daily content pipeline:
  1. Research trending signals (Google Trends, Reddit, Tavily)
  2. Synthesize content brief from signals
  3. Generate carousel content (text + image prompts)
  4. Generate AI background images
  5. Build carousel slide images
  6. Convert slides to video (for YouTube Shorts)
  7. Publish to LinkedIn (personal + company page)
  8. Upload to YouTube as a Short
  9. (Future) Publish to Instagram

Usage:
  python main.py              # Run the full pipeline once
  python main.py --dry-run    # Generate content only, no publishing
  python main.py --slides 4   # Generate 4 slides instead of default 5
  python main.py --no-ai-images  # Use gradient backgrounds instead of AI
  python main.py --no-research   # Skip research phase, use theme rotation
"""

import sys
import json
import argparse
import logging
from datetime import datetime, date
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from config.settings import Config
from content.generator import generate_content, get_todays_theme
from slides.builder import build_carousel, slides_to_video
from publishers.linkedin import post_carousel as linkedin_post
from publishers.youtube import upload_short as youtube_upload
from publishers.instagram import post_carousel as instagram_post


# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(Config.OUTPUT_DIR / "pipeline.log" if Config.OUTPUT_DIR.exists() else "pipeline.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def run_pipeline(num_slides: int = 5, dry_run: bool = False,
                  use_ai_images: bool = True, use_research: bool = True) -> dict:
    """
    Execute the full content pipeline.

    Args:
        num_slides: Number of slides to generate (3-6)
        dry_run: If True, generate content but don't publish
        use_ai_images: Use AI-generated backgrounds vs simple gradients
        use_research: Use research layer for trending content (vs theme rotation)

    Returns:
        Dict with results from each pipeline stage
    """
    results = {
        "date": date.today().isoformat(),
        "timestamp": datetime.now().isoformat(),
        "stages": {}
    }

    Config.ensure_dirs()

    # --- Validate config ---
    issues = Config.validate()
    if issues:
        for issue in issues:
            logger.warning(f"⚠️  {issue}")

    brief = None
    signals = None

    # ==========================================
    # STAGE 1: Research Trending Signals
    # ==========================================
    if use_research:
        print("\n" + "=" * 50)
        print("🔍 STAGE 1: Researching Trending Signals")
        print("=" * 50)

        try:
            from research.trending import gather_all_signals, get_signals_summary

            signals = gather_all_signals()
            results["stages"]["research"] = "success"

            # Print summary
            print(get_signals_summary(signals))

            # Save signals for reference
            signals_path = Config.OUTPUT_DIR / f"{date.today().isoformat()}_signals.json"
            with open(signals_path, "w") as f:
                json.dump(signals, f, indent=2, default=str)
            print(f"\n  💾 Signals saved to: {signals_path.name}")

        except Exception as e:
            logger.warning(f"Research phase failed, falling back to themes: {e}")
            results["stages"]["research"] = f"fallback: {e}"
            use_research = False  # Fall back to theme-based generation
    else:
        print("\n" + "=" * 50)
        print("⏭️  STAGE 1: Research (skipped)")
        print("=" * 50)
        results["stages"]["research"] = "skipped (--no-research flag)"

    # ==========================================
    # STAGE 2: Synthesize Content Brief
    # ==========================================
    if use_research and signals:
        print("\n" + "=" * 50)
        print("🧠 STAGE 2: Synthesizing Content Brief")
        print("=" * 50)

        try:
            from research.synthesizer import synthesize_brief

            brief = synthesize_brief(signals)
            results["stages"]["synthesis"] = "success"

            print(f"  📌 Trending Angle: {brief.get('trending_angle', 'N/A')}")
            print(f"  🎣 Hook: {brief.get('hook_headline', 'N/A')}")
            print(f"  🎯 Carousel Angle: {brief.get('carousel_angle', 'N/A')}")
            print(f"  🎨 Tone: {brief.get('tone', 'N/A')}")
            print(f"  📊 Why Now: {brief.get('why_this_works_today', 'N/A')}")

            # Save brief for reference
            brief_path = Config.OUTPUT_DIR / f"{date.today().isoformat()}_brief.json"
            with open(brief_path, "w") as f:
                json.dump(brief, f, indent=2)
            print(f"\n  💾 Brief saved to: {brief_path.name}")

        except Exception as e:
            logger.warning(f"Brief synthesis failed, falling back to themes: {e}")
            results["stages"]["synthesis"] = f"fallback: {e}"
            brief = None
    else:
        print("\n" + "=" * 50)
        print("⏭️  STAGE 2: Synthesis (skipped)")
        print("=" * 50)
        results["stages"]["synthesis"] = "skipped (no research data)"

    # ==========================================
    # STAGE 3: Generate Content
    # ==========================================
    print("\n" + "=" * 50)
    print("🚀 STAGE 3: Generating Content")
    print("=" * 50)

    # Show what mode we're using
    if brief:
        print("  📋 Mode: Research-driven (using content brief)")
    else:
        theme = get_todays_theme()
        print("  📋 Mode: Theme-driven (rotating themes)")
        print(f"  📌 Theme: {theme['theme']}")
        print(f"  🎯 Angle: {theme['angle']}")
        print(f"  🎣 Hook: {theme['hook_style']}")

    try:
        content = generate_content(num_slides=num_slides, brief=brief)
        results["stages"]["content_generation"] = "success"

        # Save content JSON for reference
        content_path = Config.OUTPUT_DIR / f"{date.today().isoformat()}_content.json"
        with open(content_path, "w") as f:
            json.dump(content, f, indent=2)
        print(f"\n  ✅ Content generated! ({len(content['slides'])} slides)")
        print(f"  💾 Saved to: {content_path.name}")

        # Print slide preview
        for slide in content["slides"]:
            print(f"\n  [Slide {slide['slide_number']}]")
            print(f"  {slide['text'][:80]}...")

    except Exception as e:
        logger.error(f"Content generation failed: {e}")
        results["stages"]["content_generation"] = f"error: {e}"
        return results

    # ==========================================
    # STAGE 4: Build Slides
    # ==========================================
    print("\n" + "=" * 50)
    print("🎨 STAGE 4: Building Slides")
    print("=" * 50)

    try:
        slide_paths = build_carousel(content, use_ai_images=use_ai_images)
        results["stages"]["slide_generation"] = "success"
        results["slide_paths"] = [str(p) for p in slide_paths]
        print(f"\n  ✅ {len(slide_paths)} slides built!")

    except Exception as e:
        logger.error(f"Slide generation failed: {e}")
        results["stages"]["slide_generation"] = f"error: {e}"
        return results

    # ==========================================
    # STAGE 5: Create Video (for YouTube)
    # ==========================================
    print("\n" + "=" * 50)
    print("🎬 STAGE 5: Creating Video")
    print("=" * 50)

    video_path = None
    try:
        video_path = slides_to_video(slide_paths, duration_per_slide=3.0)
        if video_path:
            results["stages"]["video_generation"] = "success"
            results["video_path"] = str(video_path)
        else:
            results["stages"]["video_generation"] = "skipped (moviepy not installed)"
    except Exception as e:
        logger.warning(f"Video generation failed (non-critical): {e}")
        results["stages"]["video_generation"] = f"error: {e}"

    if dry_run:
        print("\n" + "=" * 50)
        print("🏁 DRY RUN — Skipping publishing")
        print("=" * 50)
        results["stages"]["publishing"] = "skipped (dry run)"
        return results

    # ==========================================
    # STAGE 6: Publish to LinkedIn
    # ==========================================
    print("\n" + "=" * 50)
    print("📤 STAGE 6: Publishing to LinkedIn")
    print("=" * 50)

    if Config.LINKEDIN_ACCESS_TOKEN:
        try:
            caption = content.get("caption", "")
            hashtags = " ".join(content.get("hashtags", []))
            full_caption = f"{caption}\n\n{hashtags}"

            li_result = linkedin_post(slide_paths, full_caption)
            results["stages"]["linkedin"] = li_result
        except Exception as e:
            logger.error(f"LinkedIn publishing failed: {e}")
            results["stages"]["linkedin"] = f"error: {e}"
    else:
        print("  ⏭️  Skipping LinkedIn (not configured)")
        results["stages"]["linkedin"] = "skipped (not configured)"

    # ==========================================
    # STAGE 7: Upload to YouTube
    # ==========================================
    print("\n" + "=" * 50)
    print("📺 STAGE 7: Uploading to YouTube")
    print("=" * 50)

    # Get theme for YouTube title fallback
    theme = get_todays_theme()

    if Config.YOUTUBE_REFRESH_TOKEN and video_path:
        try:
            yt_title = content.get("youtube_title", f"Career Tips | {theme['theme']}")
            yt_desc = content.get("youtube_description",
                                   f"{content.get('caption', '')}\n\n🔗 assuredreferral.com")
            yt_tags = [tag.replace("#", "") for tag in content.get("hashtags", [])]

            yt_result = youtube_upload(video_path, yt_title, yt_desc, yt_tags)
            results["stages"]["youtube"] = yt_result
        except Exception as e:
            logger.error(f"YouTube upload failed: {e}")
            results["stages"]["youtube"] = f"error: {e}"
    else:
        reason = "not configured" if not Config.YOUTUBE_REFRESH_TOKEN else "no video generated"
        print(f"  ⏭️  Skipping YouTube ({reason})")
        results["stages"]["youtube"] = f"skipped ({reason})"

    # ==========================================
    # STAGE 8: Instagram (placeholder)
    # ==========================================
    print("\n" + "=" * 50)
    print("📸 STAGE 8: Instagram")
    print("=" * 50)

    if Config.INSTAGRAM_ACCESS_TOKEN:
        # Instagram requires public image URLs — would need image hosting
        print("  ⚠️  Instagram requires publicly hosted images. Skipping for now.")
        results["stages"]["instagram"] = "skipped (needs image hosting setup)"
    else:
        print("  ⏭️  Skipping Instagram (not configured)")
        results["stages"]["instagram"] = "skipped (not configured)"

    # ==========================================
    # Summary
    # ==========================================
    print("\n" + "=" * 50)
    print("📊 PIPELINE SUMMARY")
    print("=" * 50)
    for stage, status in results["stages"].items():
        emoji = "✅" if status == "success" or (isinstance(status, dict) and "error" not in status) else "⚠️"
        print(f"  {emoji} {stage}: {status}")

    # Save full results
    results_path = Config.OUTPUT_DIR / f"{date.today().isoformat()}_results.json"
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2, default=str)

    return results


def main():
    parser = argparse.ArgumentParser(description="AssuredReferral AutoPoster Pipeline")
    parser.add_argument("--dry-run", action="store_true",
                        help="Generate content without publishing")
    parser.add_argument("--slides", type=int, default=5,
                        help="Number of slides (3-6, default 5)")
    parser.add_argument("--no-ai-images", action="store_true",
                        help="Use gradient backgrounds instead of AI-generated images")
    parser.add_argument("--no-research", action="store_true",
                        help="Skip research phase, use theme rotation instead")

    args = parser.parse_args()

    print("\n🚀 AssuredReferral AutoPoster")
    print(f"📅 {date.today().isoformat()}")
    print(f"⏰ {datetime.now().strftime('%H:%M:%S')}")

    results = run_pipeline(
        num_slides=args.slides,
        dry_run=args.dry_run,
        use_ai_images=not args.no_ai_images,
        use_research=not args.no_research
    )

    if "error" in str(results.get("stages", {})):
        sys.exit(1)


if __name__ == "__main__":
    main()
