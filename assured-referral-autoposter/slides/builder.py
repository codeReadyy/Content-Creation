"""
Slide builder — composites text over AI-generated or gradient backgrounds.
Produces Instagram/TikTok-style carousel images (1080x1080).
"""

import io
import textwrap
from pathlib import Path
from datetime import date
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from config.settings import Config
from slides.image_gen import generate_background, generate_fallback_gradient


# Slide dimensions (Instagram carousel)
SLIDE_WIDTH = 1080
SLIDE_HEIGHT = 1080

# Font sizes
HOOK_FONT_SIZE = 58
BODY_FONT_SIZE = 44
CTA_FONT_SIZE = 40
BRAND_FONT_SIZE = 28
SLIDE_NUM_FONT_SIZE = 20


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Load a clean sans-serif font. Falls back to default if not available."""
    font_paths = [
        # Common Linux paths
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        # macOS
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial Bold.ttf" if bold else "/Library/Fonts/Arial.ttf",
    ]
    for path in font_paths:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def _add_dark_overlay(img: Image.Image, opacity: int = 160) -> Image.Image:
    """Add a semi-transparent dark overlay for text readability."""
    overlay = Image.new("RGBA", img.size, (0, 0, 0, opacity))
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    return Image.alpha_composite(img, overlay)


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Wrap text to fit within max_width pixels."""
    words = text.split()
    lines = []
    current_line = ""

    for word in words:
        test_line = f"{current_line} {word}".strip()
        bbox = font.getbbox(test_line)
        if bbox[2] <= max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = word

    if current_line:
        lines.append(current_line)

    return lines


def _draw_text_centered(draw: ImageDraw.Draw, text: str, font: ImageFont.FreeTypeFont,
                         y_start: int, max_width: int, color: str = "white",
                         line_spacing: int = 16) -> int:
    """Draw wrapped, centered text. Returns the y position after the last line."""
    lines = _wrap_text(text, font, max_width)
    y = y_start

    for line in lines:
        bbox = font.getbbox(line)
        line_width = bbox[2] - bbox[0]
        x = (SLIDE_WIDTH - line_width) // 2
        draw.text((x, y), line, fill=color, font=font)
        y += bbox[3] - bbox[1] + line_spacing

    return y


def build_slide(slide_data: dict, slide_index: int, total_slides: int,
                bg_image_bytes: bytes = None, is_hook: bool = False,
                is_cta: bool = False) -> Image.Image:
    """
    Build a single carousel slide image.

    Args:
        slide_data: Dict with 'text' and optionally 'image_prompt'
        slide_index: 0-based slide index
        total_slides: Total number of slides
        bg_image_bytes: Pre-generated background image bytes
        is_hook: True if this is the first (hook) slide
        is_cta: True if this is the last (CTA) slide
    """
    # Load or create background
    if bg_image_bytes:
        bg = Image.open(io.BytesIO(bg_image_bytes)).resize((SLIDE_WIDTH, SLIDE_HEIGHT))
    else:
        fallback = generate_fallback_gradient()
        bg = Image.open(io.BytesIO(fallback)).resize((SLIDE_WIDTH, SLIDE_HEIGHT))

    # Add dark overlay for text readability
    img = _add_dark_overlay(bg, opacity=150 if is_hook else 140)
    draw = ImageDraw.Draw(img)

    # Choose font size based on slide type
    if is_hook:
        main_font = _load_font(HOOK_FONT_SIZE, bold=True)
    elif is_cta:
        main_font = _load_font(CTA_FONT_SIZE, bold=True)
    else:
        main_font = _load_font(BODY_FONT_SIZE, bold=False)

    brand_font = _load_font(BRAND_FONT_SIZE, bold=True)
    num_font = _load_font(SLIDE_NUM_FONT_SIZE, bold=False)

    # Text margins
    margin_x = 80
    max_text_width = SLIDE_WIDTH - 2 * margin_x

    # Calculate vertical centering
    text = slide_data["text"]
    lines = _wrap_text(text, main_font, max_text_width)
    line_height = main_font.getbbox("Ay")[3] - main_font.getbbox("Ay")[1] + 16
    total_text_height = len(lines) * line_height
    y_start = (SLIDE_HEIGHT - total_text_height) // 2 - 30

    # Draw main text
    _draw_text_centered(draw, text, main_font, y_start, max_text_width)

    # Slide number indicator (bottom left)
    slide_num_text = f"{slide_index + 1}/{total_slides}"
    draw.text((margin_x, SLIDE_HEIGHT - 60), slide_num_text,
              fill=(255, 255, 255, 180), font=num_font)

    # Brand watermark (bottom right) — always present
    brand_text = Config.BRAND_NAME
    bbox = brand_font.getbbox(brand_text)
    brand_width = bbox[2] - bbox[0]
    draw.text((SLIDE_WIDTH - margin_x - brand_width, SLIDE_HEIGHT - 65),
              brand_text, fill=(255, 255, 255, 200), font=brand_font)

    # Add subtle accent line on hook slide
    if is_hook:
        accent_y = y_start - 30
        line_width = 60
        line_x = (SLIDE_WIDTH - line_width) // 2
        draw.line([(line_x, accent_y), (line_x + line_width, accent_y)],
                  fill=(99, 102, 241), width=4)

    return img.convert("RGB")


def build_carousel(content: dict, use_ai_images: bool = True) -> list[Path]:
    """
    Build all slides for a carousel post.

    Args:
        content: Output from content generator with 'slides' list
        use_ai_images: Whether to generate AI backgrounds (costs API credits)

    Returns:
        List of file paths to saved slide images
    """
    Config.ensure_dirs()
    today = date.today().isoformat()
    slides = content["slides"]
    saved_paths = []

    for i, slide in enumerate(slides):
        is_hook = (i == 0)
        is_cta = (i == len(slides) - 1)

        # Generate background image
        bg_bytes = None
        if use_ai_images:
            try:
                prompt = slide.get("image_prompt", "abstract professional gradient")
                bg_bytes = generate_background(prompt)
                print(f"  ✓ Generated AI background for slide {i + 1}")
            except Exception as e:
                print(f"  ⚠ AI image failed for slide {i + 1}, using fallback: {e}")
                bg_bytes = generate_fallback_gradient()
        else:
            bg_bytes = generate_fallback_gradient()

        # Build the slide
        img = build_slide(slide, i, len(slides), bg_bytes, is_hook, is_cta)

        # Save
        save_path = Config.SLIDES_DIR / f"{today}_slide_{i + 1}.png"
        img.save(save_path, "PNG", quality=95)
        saved_paths.append(save_path)
        print(f"  ✓ Saved slide {i + 1}: {save_path.name}")

    return saved_paths


def slides_to_video(slide_paths: list[Path], duration_per_slide: float = 3.0) -> Path:
    """
    Convert slide images into an MP4 video (for YouTube Shorts).
    Each slide is shown for `duration_per_slide` seconds.

    Requires: pip install moviepy
    """
    try:
        from moviepy.editor import ImageClip, concatenate_videoclips

        clips = []
        for path in slide_paths:
            clip = ImageClip(str(path), duration=duration_per_slide)
            # Resize to 1080x1920 (9:16 vertical for Shorts)
            clip = clip.resize(height=1920).on_color(
                size=(1080, 1920), color=(0, 0, 0), pos="center"
            )
            clips.append(clip)

        video = concatenate_videoclips(clips, method="compose")

        today = date.today().isoformat()
        video_path = Config.VIDEOS_DIR / f"{today}_short.mp4"
        video.write_videofile(
            str(video_path),
            fps=24,
            codec="libx264",
            audio=False,
            logger=None
        )
        video.close()

        print(f"  ✓ Video saved: {video_path.name}")
        return video_path

    except ImportError:
        print("  ⚠ moviepy not installed. Skipping video generation.")
        print("    Install with: pip install moviepy")
        return None


if __name__ == "__main__":
    # Test with dummy content
    test_content = {
        "slides": [
            {"slide_number": 1, "text": "80% of jobs are filled through referrals.\n\nYet most people still apply cold.", "image_prompt": "dark blue abstract network connections"},
            {"slide_number": 2, "text": "The truth?\n\nYour resume isn't the problem.\nYour strategy is.", "image_prompt": "minimal geometric shapes on dark background"},
            {"slide_number": 3, "text": "Step 1: Stop mass-applying\nStep 2: Find the right insider\nStep 3: Get a warm introduction", "image_prompt": "ascending staircase, modern minimal"},
            {"slide_number": 4, "text": "We built AssuredReferral to make this effortless.\n\nConnect → Get Referred → Get Hired\n\n🔗 assuredreferral.com", "image_prompt": "warm gradient, professional, hopeful"},
        ]
    }
    paths = build_carousel(test_content, use_ai_images=False)
    print(f"\nGenerated {len(paths)} slides!")
