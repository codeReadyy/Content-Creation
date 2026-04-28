#!/usr/bin/env python3
"""
Multi-product pipeline runner.
Entry point for GitHub Actions workflows.

Usage:
  python runner.py --product assuredreferral --platforms linkedin,youtube
  python runner.py --product assuredreferral --platforms instagram --dry-run
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
from config.product_loader import load_product, list_products
from content.generator import generate_content, get_todays_theme
from slides.builder import build_carousel, slides_to_video, slides_to_pdf
from publishers.linkedin import post_carousel as linkedin_post
from publishers.youtube import upload_short as youtube_upload
from publishers.instagram import post_carousel as instagram_post
from publishers.telegram_notifier import notify_pipeline_result


def run_pipeline(
    product_id: str,
    platforms: list[str],
    num_slides: int = 5,
    dry_run: bool = False,
    use_ai_images: bool = True,
    use_research: bool = True
) -> dict:
    """
    Execute the content pipeline for a specific product and platforms.

    Args:
        product_id: Product ID (e.g., 'assuredreferral')
        platforms: List of platforms to publish to (e.g., ['linkedin', 'youtube'])
        num_slides: Number of slides to generate (3-6)
        dry_run: If True, generate content but don't publish
        use_ai_images: Use AI-generated backgrounds vs simple gradients
        use_research: Use research layer for trending content

    Returns:
        Dict with results from each pipeline stage
    """
    results = {
        "product": product_id,
        "platforms": platforms,
        "date": date.today().isoformat(),
        "timestamp": datetime.now().isoformat(),
        "stages": {}
    }

    # Load product config and set it as active
    try:
        Config.set_product(product_id)
        product = Config.get_product()
        print(f"\n{'=' * 50}")
        print(f"Product: {product.name}")
        print(f"Platforms: {', '.join(platforms)}")
        print(f"{'=' * 50}")
    except FileNotFoundError:
        print(f"Error: Product '{product_id}' not found")
        print(f"Available products: {list_products()}")
        return {"error": f"Product not found: {product_id}"}

    Config.ensure_dirs()

    # Validate config
    issues = Config.validate(product_id)
    if issues:
        for issue in issues:
            print(f"  Warning: {issue}")

    brief = None
    signals = None

    # ==========================================
    # STAGE 1: Research Trending Signals
    # ==========================================
    if use_research:
        print(f"\n{'=' * 50}")
        print("STAGE 1: Researching Trending Signals")
        print("=" * 50)

        try:
            from research.trending import gather_all_signals, get_signals_summary

            signals = gather_all_signals()
            results["stages"]["research"] = "success"
            print(get_signals_summary(signals))

            signals_path = Config.OUTPUT_DIR / f"{date.today().isoformat()}_signals.json"
            with open(signals_path, "w") as f:
                json.dump(signals, f, indent=2, default=str)

        except Exception as e:
            print(f"  Research failed, falling back to themes: {e}")
            results["stages"]["research"] = f"fallback: {e}"
            use_research = False
    else:
        results["stages"]["research"] = "skipped"

    # ==========================================
    # STAGE 2: Synthesize Content Brief
    # ==========================================
    if use_research and signals:
        print(f"\n{'=' * 50}")
        print("STAGE 2: Synthesizing Content Brief")
        print("=" * 50)

        try:
            from research.synthesizer import synthesize_brief

            brief = synthesize_brief(signals)
            results["stages"]["synthesis"] = "success"

            brief_path = Config.OUTPUT_DIR / f"{date.today().isoformat()}_brief.json"
            with open(brief_path, "w") as f:
                json.dump(brief, f, indent=2)

        except Exception as e:
            print(f"  Brief synthesis failed: {e}")
            results["stages"]["synthesis"] = f"fallback: {e}"
            brief = None
    else:
        results["stages"]["synthesis"] = "skipped"

    # ==========================================
    # STAGE 3: Generate Content
    # ==========================================
    print(f"\n{'=' * 50}")
    print("STAGE 3: Generating Content")
    print("=" * 50)

    try:
        content = generate_content(num_slides=num_slides, brief=brief)
        results["stages"]["content_generation"] = "success"

        content_path = Config.OUTPUT_DIR / f"{date.today().isoformat()}_content.json"
        with open(content_path, "w") as f:
            json.dump(content, f, indent=2)
        print(f"  Content generated! ({len(content['slides'])} slides)")

    except Exception as e:
        print(f"  Content generation failed: {e}")
        results["stages"]["content_generation"] = f"error: {e}"
        return results

    # ==========================================
    # STAGE 4: Build Slides
    # ==========================================
    print(f"\n{'=' * 50}")
    print("STAGE 4: Building Slides")
    print("=" * 50)

    try:
        slide_paths = build_carousel(content, use_ai_images=use_ai_images)
        results["stages"]["slide_generation"] = "success"
        results["slide_paths"] = [str(p) for p in slide_paths]

        pdf_path = slides_to_pdf(slide_paths)
        if pdf_path:
            results["pdf_path"] = str(pdf_path)

    except Exception as e:
        print(f"  Slide generation failed: {e}")
        results["stages"]["slide_generation"] = f"error: {e}"
        return results

    # ==========================================
    # STAGE 5: Create Video (if YouTube in platforms)
    # ==========================================
    video_path = None
    if "youtube" in platforms:
        print(f"\n{'=' * 50}")
        print("STAGE 5: Creating Video")
        print("=" * 50)

        try:
            video_path = slides_to_video(slide_paths, duration_per_slide=3.0)
            if video_path:
                results["stages"]["video_generation"] = "success"
                results["video_path"] = str(video_path)
            else:
                results["stages"]["video_generation"] = "skipped (moviepy not installed)"
        except Exception as e:
            print(f"  Video generation failed: {e}")
            results["stages"]["video_generation"] = f"error: {e}"
    else:
        results["stages"]["video_generation"] = "skipped (youtube not in platforms)"

    if dry_run:
        print(f"\n{'=' * 50}")
        print("DRY RUN - Skipping publishing")
        print("=" * 50)
        results["stages"]["publishing"] = "skipped (dry run)"
        return results

    # ==========================================
    # STAGE 6: Publish to Platforms
    # ==========================================
    caption = content.get("caption", "")
    hashtags = " ".join(content.get("hashtags", []))
    full_caption = f"{caption}\n\n{hashtags}"

    # LinkedIn
    if "linkedin" in platforms:
        print(f"\n{'=' * 50}")
        print("Publishing to LinkedIn")
        print("=" * 50)

        li_creds = product.get_linkedin_credentials()
        if li_creds.get("access_token"):
            try:
                pdf_path_obj = Path(results.get("pdf_path", "")) if results.get("pdf_path") else None
                li_result = linkedin_post(slide_paths, full_caption, pdf_path=pdf_path_obj)
                results["stages"]["linkedin"] = li_result
            except Exception as e:
                results["stages"]["linkedin"] = f"error: {e}"
        else:
            results["stages"]["linkedin"] = "skipped (not configured)"

    # YouTube
    if "youtube" in platforms and video_path:
        print(f"\n{'=' * 50}")
        print("Uploading to YouTube")
        print("=" * 50)

        yt_creds = product.get_youtube_credentials()
        if yt_creds.get("refresh_token"):
            try:
                yt_title = content.get("youtube_title", f"Career Tips | {product.name}")
                yt_desc = content.get("youtube_description", f"{caption}\n\n{product.url}")
                yt_tags = [tag.replace("#", "") for tag in content.get("hashtags", [])]
                yt_result = youtube_upload(video_path, yt_title, yt_desc, yt_tags)
                results["stages"]["youtube"] = yt_result
            except Exception as e:
                results["stages"]["youtube"] = f"error: {e}"
        else:
            results["stages"]["youtube"] = "skipped (not configured)"

    # Instagram
    if "instagram" in platforms:
        print(f"\n{'=' * 50}")
        print("Publishing to Instagram")
        print("=" * 50)

        ig_creds = product.get_instagram_credentials()
        if ig_creds.get("access_token"):
            # Note: Instagram requires publicly hosted images
            print("  Instagram requires publicly hosted images - skipping for now")
            results["stages"]["instagram"] = "skipped (needs image hosting)"
        else:
            results["stages"]["instagram"] = "skipped (not configured)"

    # ==========================================
    # Summary
    # ==========================================
    print(f"\n{'=' * 50}")
    print("PIPELINE SUMMARY")
    print("=" * 50)
    for stage, status in results["stages"].items():
        emoji = "OK" if status == "success" or (isinstance(status, dict) and "error" not in status) else "!!"
        print(f"  [{emoji}] {stage}: {status}")

    # Save results
    results_path = Config.OUTPUT_DIR / f"{date.today().isoformat()}_results.json"
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2, default=str)

    return results


def main():
    parser = argparse.ArgumentParser(description="Multi-product content pipeline runner")
    parser.add_argument("--product", required=True, help="Product ID (e.g., assuredreferral)")
    parser.add_argument("--platforms", required=True, help="Comma-separated platforms (e.g., linkedin,youtube)")
    parser.add_argument("--dry-run", action="store_true", help="Generate content without publishing")
    parser.add_argument("--slides", type=int, default=5, help="Number of slides (3-6)")
    parser.add_argument("--no-ai-images", action="store_true", help="Use gradient backgrounds")
    parser.add_argument("--no-research", action="store_true", help="Skip research phase")

    args = parser.parse_args()

    platforms = [p.strip().lower() for p in args.platforms.split(",")]

    print(f"\nMulti-Product Pipeline Runner")
    print(f"Date: {date.today().isoformat()}")
    print(f"Time: {datetime.now().strftime('%H:%M:%S')}")

    results = run_pipeline(
        product_id=args.product,
        platforms=platforms,
        num_slides=args.slides,
        dry_run=args.dry_run,
        use_ai_images=not args.no_ai_images,
        use_research=not args.no_research
    )

    # Send Telegram notification
    print("\nSending Telegram notification...")
    notify_result = notify_pipeline_result(results)
    if "error" in notify_result:
        print(f"  Telegram: {notify_result['error']}")
    else:
        print("  Telegram notification sent!")

    if "error" in str(results.get("stages", {})):
        sys.exit(1)


if __name__ == "__main__":
    main()
