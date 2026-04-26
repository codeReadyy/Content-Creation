"""
Slide builder — LinkedIn/Instagram carousel images.
Design: Full-bleed darkened image with text overlay at bottom.
Produces 1080x1350 (4:5) images and PDF for LinkedIn carousels.
Also generates YouTube Shorts videos (1080x1920).
"""

import io
import re
import random
from pathlib import Path
from datetime import date
from PIL import Image, ImageDraw, ImageFont, ImageEnhance
from config.settings import Config
from slides.image_gen import generate_background, generate_fallback_gradient


# Slide dimensions (4:5 aspect ratio for LinkedIn/Instagram)
SLIDE_WIDTH = 1080
SLIDE_HEIGHT = 1350  # 4:5 aspect ratio

# Font sizes (bold, impactful)
HEADLINE_FONT_SIZE = 54
BODY_FONT_SIZE = 46
SUBTEXT_FONT_SIZE = 32
BRAND_FONT_SIZE = 26

# Colors
TEXT_COLOR = (255, 255, 255)  # White
ACCENT_COLOR = (0, 210, 180)  # Teal/cyan (#00D2B4) - matches reference

# Margins
MARGIN_X = 60
MARGIN_Y = 50

# Text area starts at this percentage from bottom
TEXT_AREA_BOTTOM_PERCENT = 0.38  # Text occupies bottom 38% of slide

# Path to background music folder
MUSIC_DIR = Path(__file__).parent.parent / "assets" / "music"


def _load_font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    """Load a bold sans-serif font. Falls back to default if not available."""
    font_paths = [
        # macOS - prefer bold/heavy weights
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        # Linux
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        # Fallback
        "/System/Library/Fonts/SFCompact.ttf",
    ]
    for path in font_paths:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


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


def _find_accent_words(text: str) -> list[str]:
    """
    Find words/phrases that should be highlighted with accent color.
    Returns uppercase versions for consistent matching.
    """
    accent_patterns = [
        r'\$[\d,]+[kK]?',           # Money: $99K, $1,000
        r'\d+%',                     # Percentages: 80%
        r'\d+\s*(days?|weeks?|months?|years?|hours?)',  # Time: 30 days
        r'\d+\s*(job|offer|interview|referral)s?',      # Counts: 3 job offers
        r'\d+x',                     # Multipliers: 10x
        r'#\d+',                     # Rankings: #1
    ]

    # Key phrases to highlight
    key_phrases = [
        'referral', 'referrals', 'referred', 'hired', 'offer', 'offers',
        'interview', 'interviews', 'salary', 'networking', 'network',
        'assuredreferral', 'job', 'jobs', 'career', 'rewarded',
        'assuredreferral.com', 'ai-driven',
    ]

    accent_words = set()

    # Find pattern matches
    for pattern in accent_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for match in matches:
            accent_words.add(match.upper())

    # Find key phrases - store uppercase versions
    text_lower = text.lower()
    for phrase in key_phrases:
        if phrase in text_lower:
            accent_words.add(phrase.upper())

    return list(accent_words)


def _draw_text_with_accents(
    draw: ImageDraw.Draw,
    text: str,
    font: ImageFont.FreeTypeFont,
    y_start: int,
    max_width: int,
    line_spacing: int = 20,
    uppercase: bool = True
) -> int:
    """
    Draw text with accent-colored keywords. Returns y position after last line.
    """
    if uppercase:
        display_text = text.upper()
    else:
        display_text = text

    # Get accent words (already uppercase from _find_accent_words)
    accent_words = _find_accent_words(text)
    lines = _wrap_text(display_text, font, max_width)
    y = y_start

    for line in lines:
        # Calculate line width for centering
        bbox = font.getbbox(line)
        line_width = bbox[2] - bbox[0]
        x = (SLIDE_WIDTH - line_width) // 2

        # Check if this line contains any accent words
        line_check = line.upper()
        has_accent = any(accent in line_check for accent in accent_words)

        if has_accent:
            # Draw word by word with color changes
            current_x = x
            words = line.split()
            for word in words:
                word_color = TEXT_COLOR
                word_clean = re.sub(r'[^\w]', '', word.upper())  # Remove punctuation

                # Check if this word matches any accent word
                for accent in accent_words:
                    if accent in word_clean or word_clean in accent:
                        word_color = ACCENT_COLOR
                        break

                draw.text((current_x, y), word, fill=word_color, font=font)
                word_bbox = font.getbbox(word + " ")
                current_x += word_bbox[2] - word_bbox[0]
        else:
            # Draw entire line in white
            draw.text((x, y), line, fill=TEXT_COLOR, font=font)

        y += bbox[3] - bbox[1] + line_spacing

    return y


def _process_background_full_bleed(img_bytes: bytes) -> Image.Image:
    """
    Process background image for full-bleed effect:
    - Resize to cover entire slide
    - Convert to grayscale/desaturated
    - Darken for text readability
    - Add gradient fade at bottom
    """
    img = Image.open(io.BytesIO(img_bytes))

    if img.mode != "RGB":
        img = img.convert("RGB")

    # Resize to cover entire slide (crop to fit)
    img_ratio = img.width / img.height
    slide_ratio = SLIDE_WIDTH / SLIDE_HEIGHT

    if img_ratio > slide_ratio:
        # Image is wider - fit by height
        new_height = SLIDE_HEIGHT
        new_width = int(new_height * img_ratio)
    else:
        # Image is taller - fit by width
        new_width = SLIDE_WIDTH
        new_height = int(new_width / img_ratio)

    img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

    # Center crop to slide dimensions
    left = (new_width - SLIDE_WIDTH) // 2
    top = (new_height - SLIDE_HEIGHT) // 2
    img = img.crop((left, top, left + SLIDE_WIDTH, top + SLIDE_HEIGHT))

    # Desaturate (convert to grayscale and back to RGB for that B&W look)
    grayscale = img.convert("L")
    img = grayscale.convert("RGB")

    # Darken the image
    enhancer = ImageEnhance.Brightness(img)
    img = enhancer.enhance(0.45)  # 45% brightness (darker)

    # Add slight contrast
    enhancer = ImageEnhance.Contrast(img)
    img = enhancer.enhance(1.2)

    return img


def _add_bottom_gradient(img: Image.Image) -> Image.Image:
    """
    Add a gradient fade at the bottom of the image for text readability.
    Gradient goes from transparent at top to dark at bottom.
    """
    if img.mode != "RGBA":
        img = img.convert("RGBA")

    width, height = img.size

    # Create gradient overlay
    gradient = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(gradient)

    # Gradient starts at 45% from top, fades to nearly opaque at bottom
    gradient_start = int(height * 0.45)
    gradient_end = height

    for y in range(gradient_start, gradient_end):
        progress = (y - gradient_start) / (gradient_end - gradient_start)
        # Ease-in curve for smoother transition
        alpha = int(200 * (progress ** 1.3))  # Max 200 alpha (not fully opaque)
        alpha = min(200, max(0, alpha))
        draw.line([(0, y), (width, y)], fill=(0, 0, 0, alpha))

    # Composite gradient over image
    img = Image.alpha_composite(img, gradient)

    return img.convert("RGB")


def build_slide(
    slide_data: dict,
    slide_index: int,
    total_slides: int,
    bg_image_bytes: bytes = None,
    is_hook: bool = False,
    is_cta: bool = False
) -> Image.Image:
    """
    Build a single carousel slide image with full-bleed background.
    Darkened grayscale image with text overlay at bottom.
    """
    # Create base canvas
    img = Image.new("RGB", (SLIDE_WIDTH, SLIDE_HEIGHT), (20, 20, 20))

    # Process and place full-bleed background image
    if bg_image_bytes:
        try:
            img = _process_background_full_bleed(bg_image_bytes)
            img = _add_bottom_gradient(img)
        except Exception as e:
            print(f"  Warning: Could not process background image: {e}")

    draw = ImageDraw.Draw(img)

    # Load fonts
    if is_hook:
        main_font = _load_font(HEADLINE_FONT_SIZE, bold=True)
    else:
        main_font = _load_font(BODY_FONT_SIZE, bold=True)

    brand_font = _load_font(BRAND_FONT_SIZE, bold=True)
    subtext_font = _load_font(SUBTEXT_FONT_SIZE, bold=False)

    # Text area positioning (bottom portion of slide)
    text_area_top = int(SLIDE_HEIGHT * (1 - TEXT_AREA_BOTTOM_PERCENT))
    max_text_width = SLIDE_WIDTH - 2 * MARGIN_X

    # Get slide text
    text = slide_data.get("text", "")

    # Split into main headline and subtext if there's a clear break
    lines = text.split('\n')
    main_text = lines[0] if lines else text
    subtext = '\n'.join(lines[1:]).strip() if len(lines) > 1 else ""

    # Draw main text (bold, uppercase, with accents)
    y_pos = text_area_top
    y_pos = _draw_text_with_accents(
        draw, main_text, main_font, y_pos, max_text_width,
        line_spacing=16, uppercase=True
    )

    # Draw subtext if present (smaller, mixed case)
    if subtext:
        y_pos += 25
        y_pos = _draw_text_with_accents(
            draw, subtext, subtext_font, y_pos, max_text_width,
            line_spacing=12, uppercase=False
        )

    # Brand watermark (top left)
    brand_text = Config.BRAND_NAME
    draw.text((MARGIN_X, MARGIN_Y), brand_text, fill=TEXT_COLOR, font=brand_font)

    # Slide indicator dots (bottom center)
    dot_y = SLIDE_HEIGHT - 45
    dot_spacing = 14
    dot_radius = 5
    total_dot_width = (total_slides * 2 * dot_radius) + ((total_slides - 1) * dot_spacing)
    dot_start_x = (SLIDE_WIDTH - total_dot_width) // 2

    for i in range(total_slides):
        dot_x = dot_start_x + i * (2 * dot_radius + dot_spacing) + dot_radius
        if i == slide_index:
            draw.ellipse(
                [(dot_x - dot_radius, dot_y - dot_radius),
                 (dot_x + dot_radius, dot_y + dot_radius)],
                fill=TEXT_COLOR
            )
        else:
            draw.ellipse(
                [(dot_x - dot_radius, dot_y - dot_radius),
                 (dot_x + dot_radius, dot_y + dot_radius)],
                fill=(100, 100, 100)
            )

    return img


def _extract_theme_from_content(content: dict) -> str:
    """Extract theme from content for better image searches."""
    slides = content.get("slides", [])
    if slides:
        first_slide = slides[0].get("text", "").lower()
        themes = ["interview", "referral", "salary", "resume", "networking",
                  "remote", "career", "layoff", "job search", "hiring"]
        for theme in themes:
            if theme in first_slide:
                return theme
    return "career"


def build_carousel(content: dict, use_ai_images: bool = True) -> list[Path]:
    """
    Build all slides for a carousel post.

    Args:
        content: Output from content generator with 'slides' list
        use_ai_images: Whether to generate AI/stock backgrounds

    Returns:
        List of file paths to saved slide images
    """
    Config.ensure_dirs()
    today = date.today().isoformat()
    slides = content["slides"]
    saved_paths = []

    theme = _extract_theme_from_content(content)

    for i, slide in enumerate(slides):
        is_hook = (i == 0)
        is_cta = (i == len(slides) - 1)

        # Generate background image
        bg_bytes = None
        if use_ai_images:
            try:
                prompt = slide.get("image_prompt", "professional aesthetic")
                bg_bytes = generate_background(prompt=prompt, theme=theme)
                print(f"  ✓ Generated background for slide {i + 1}")
            except Exception as e:
                print(f"  ⚠ Image failed for slide {i + 1}: {e}")

        # Build the slide
        img = build_slide(slide, i, len(slides), bg_bytes, is_hook, is_cta)

        # Save
        save_path = Config.SLIDES_DIR / f"{today}_slide_{i + 1}.png"
        img.save(save_path, "PNG", quality=95)
        saved_paths.append(save_path)
        print(f"  ✓ Saved slide {i + 1}: {save_path.name}")

    return saved_paths


def slides_to_pdf(slide_paths: list[Path]) -> Path:
    """
    Combine slide images into a PDF for LinkedIn carousel.

    Args:
        slide_paths: List of paths to slide images

    Returns:
        Path to the generated PDF file
    """
    if not slide_paths:
        return None

    today = date.today().isoformat()
    pdf_path = Config.SLIDES_DIR / f"{today}_carousel.pdf"

    # Load all images
    images = []
    for path in slide_paths:
        img = Image.open(path)
        if img.mode != "RGB":
            img = img.convert("RGB")
        images.append(img)

    # Save as PDF (first image, append rest)
    if images:
        images[0].save(
            pdf_path,
            "PDF",
            save_all=True,
            append_images=images[1:] if len(images) > 1 else [],
            resolution=100.0
        )
        print(f"  ✓ PDF carousel saved: {pdf_path.name}")

    return pdf_path


def _get_background_music() -> Path | None:
    """Get a background music file for videos."""
    if not MUSIC_DIR.exists():
        return None

    music_files = list(MUSIC_DIR.glob("*.mp3")) + list(MUSIC_DIR.glob("*.wav"))
    if not music_files:
        return None

    return random.choice(music_files)


def _download_free_music() -> Path | None:
    """Download a royalty-free music track if none exists."""
    import requests

    MUSIC_DIR.mkdir(parents=True, exist_ok=True)

    existing = list(MUSIC_DIR.glob("*.mp3"))
    if existing:
        return existing[0]

    free_tracks = [
        {
            "name": "upbeat_corporate.mp3",
            "url": "https://cdn.pixabay.com/download/audio/2022/05/27/audio_1808fbf07a.mp3"
        },
        {
            "name": "inspiring_cinematic.mp3",
            "url": "https://cdn.pixabay.com/download/audio/2022/03/15/audio_942968dcb1.mp3"
        },
        {
            "name": "motivational_uplifting.mp3",
            "url": "https://cdn.pixabay.com/download/audio/2021/11/25/audio_91b32e02f9.mp3"
        },
    ]

    track = random.choice(free_tracks)

    try:
        print(f"  ⬇ Downloading background music: {track['name']}")
        response = requests.get(track["url"], timeout=30)
        response.raise_for_status()

        music_path = MUSIC_DIR / track["name"]
        music_path.write_bytes(response.content)
        print(f"  ✓ Music downloaded: {music_path.name}")
        return music_path
    except Exception as e:
        print(f"  ⚠ Failed to download music: {e}")
        return None


def slides_to_video(
    slide_paths: list[Path],
    duration_per_slide: float = 3.0,
    add_music: bool = True,
) -> Path:
    """
    Convert slide images into a YouTube Shorts MP4 video (1080x1920 vertical).
    Includes safe margins to prevent text cutoff.
    """
    try:
        from moviepy import (
            ImageClip, concatenate_videoclips, ColorClip,
            CompositeVideoClip, AudioFileClip, CompositeAudioClip
        )

        # Video dimensions for YouTube Shorts (9:16 vertical)
        VIDEO_WIDTH = 1080
        VIDEO_HEIGHT = 1920

        clips = []
        for path in slide_paths:
            # Load slide image
            slide_clip = ImageClip(str(path), duration=duration_per_slide)

            # Scale slide to fit width with safe margins (92% for safety)
            scale_factor = (VIDEO_WIDTH * 0.92) / SLIDE_WIDTH
            new_size = (int(SLIDE_WIDTH * scale_factor), int(SLIDE_HEIGHT * scale_factor))
            slide_clip = slide_clip.resized(new_size)

            # Create dark background
            bg = ColorClip(size=(VIDEO_WIDTH, VIDEO_HEIGHT), color=(15, 15, 15), duration=duration_per_slide)

            # Center the slide vertically
            composite = CompositeVideoClip([bg, slide_clip.with_position("center")])
            clips.append(composite)

        video = concatenate_videoclips(clips)
        video_duration = video.duration

        # Add background music
        audio_clip = None
        if add_music:
            music_path = _get_background_music()
            if not music_path:
                music_path = _download_free_music()

            if music_path:
                try:
                    audio_clip = AudioFileClip(str(music_path))
                    if audio_clip.duration < video_duration:
                        loops_needed = int(video_duration / audio_clip.duration) + 1
                        audio_clip = CompositeAudioClip([
                            audio_clip.with_start(i * audio_clip.duration)
                            for i in range(loops_needed)
                        ]).with_duration(video_duration)
                    else:
                        audio_clip = audio_clip.subclipped(0, video_duration)

                    audio_clip = audio_clip.with_volume_scaled(0.3)
                    video = video.with_audio(audio_clip)
                    print(f"  ✓ Added background music")
                except Exception as e:
                    print(f"  ⚠ Failed to add music: {e}")

        today = date.today().isoformat()
        video_path = Config.VIDEOS_DIR / f"{today}_short.mp4"
        video.write_videofile(
            str(video_path),
            fps=24,
            codec="libx264",
            audio_codec="aac" if audio_clip else None,
            logger=None
        )

        video.close()
        for clip in clips:
            clip.close()
        if audio_clip:
            audio_clip.close()

        print(f"  ✓ Video saved: {video_path.name}")
        return video_path

    except ImportError:
        print("  ⚠ moviepy not installed. Skipping video generation.")
        print("    Install with: pip install 'moviepy>=2.0'")
        return None


if __name__ == "__main__":
    # Test with dummy content
    test_content = {
        "slides": [
            {"slide_number": 1, "text": "80% of jobs are filled through referrals.\n\nYet most people still apply cold.", "image_prompt": "professional networking event"},
            {"slide_number": 2, "text": "The truth?\n\nYour resume isn't the problem.\nYour strategy is.", "image_prompt": "business strategy meeting"},
            {"slide_number": 3, "text": "Step 1: Stop mass-applying\nStep 2: Find the right insider\nStep 3: Get a warm introduction", "image_prompt": "career success"},
            {"slide_number": 4, "text": "We built AssuredReferral to make this effortless.\n\nConnect → Get Referred → Get Hired\n\nassuredreferral.com", "image_prompt": "professional handshake"},
        ]
    }
    paths = build_carousel(test_content, use_ai_images=False)
    print(f"\nGenerated {len(paths)} slides!")

    # Generate PDF
    pdf_path = slides_to_pdf(paths)
    print(f"PDF: {pdf_path}")
