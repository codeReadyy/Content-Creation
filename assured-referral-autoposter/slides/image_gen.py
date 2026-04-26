"""
Image generation for slide backgrounds.
Supports:
- Unsplash API (free, aesthetic stock photos)
- Pexels API (free, aesthetic stock photos)
- Azure OpenAI gpt-image-1
- Stability AI
- Local gradient fallback
"""

import io
import base64
import random
import requests
from pathlib import Path
from PIL import Image, ImageFilter, ImageEnhance
from openai import AzureOpenAI
from config.settings import Config

# Aesthetic search queries for career/business content
# Using simple, reliable search terms that return good results
AESTHETIC_QUERIES = {
    "default": [
        "business people",
        "office meeting",
        "laptop work",
        "professional team",
        "corporate office",
        "success celebration",
        "handshake business",
        "workspace desk",
    ],
    "interview": [
        "business meeting",
        "office conversation",
        "professional person",
        "corporate meeting",
        "business discussion",
    ],
    "referral": [
        "networking event",
        "business handshake",
        "team meeting",
        "professional networking",
        "business connection",
    ],
    "salary": [
        "business success",
        "professional meeting",
        "corporate office",
        "finance business",
        "executive meeting",
    ],
    "remote": [
        "home office",
        "laptop coffee",
        "remote work",
        "working from home",
        "home workspace",
    ],
    "career": [
        "business success",
        "professional growth",
        "office team",
        "career achievement",
        "business celebration",
    ],
    "networking": [
        "business event",
        "professional meetup",
        "conference people",
        "business networking",
        "corporate event",
    ],
    "resume": [
        "office desk",
        "laptop workspace",
        "business document",
        "professional desk",
        "work planning",
    ],
    "layoff": [
        "new beginning",
        "sunrise motivation",
        "fresh start",
        "positive thinking",
        "hope future",
    ],
}


def get_search_query(theme: str = None, prompt: str = None) -> str:
    """Get an appropriate search query based on theme or prompt."""
    # Try to match theme to predefined queries
    if theme:
        theme_lower = theme.lower()
        for key, queries in AESTHETIC_QUERIES.items():
            if key in theme_lower:
                return random.choice(queries)

    # Extract keywords from prompt if provided
    if prompt:
        prompt_lower = prompt.lower()
        for key, queries in AESTHETIC_QUERIES.items():
            if key in prompt_lower:
                return random.choice(queries)

    # Default to aesthetic business/career images
    return random.choice(AESTHETIC_QUERIES["default"])


def fetch_unsplash_image(query: str, size: tuple = (1080, 1080)) -> bytes:
    """
    Fetch a high-quality image from Unsplash API.
    Free tier: 50 requests/hour.
    """
    if not Config.UNSPLASH_ACCESS_KEY:
        raise ValueError("UNSPLASH_ACCESS_KEY not configured")

    # Search for photos
    search_url = "https://api.unsplash.com/search/photos"
    params = {
        "query": query,
        "per_page": 10,
        "orientation": "squarish",
        "content_filter": "high",
    }
    headers = {
        "Authorization": f"Client-ID {Config.UNSPLASH_ACCESS_KEY}"
    }

    response = requests.get(search_url, params=params, headers=headers, timeout=15)
    response.raise_for_status()

    results = response.json().get("results", [])
    if not results:
        raise ValueError(f"No images found for query: {query}")

    # Pick a random image from results
    photo = random.choice(results[:5])
    image_url = photo["urls"]["regular"]  # 1080px width

    # Download the image
    img_response = requests.get(image_url, timeout=30)
    img_response.raise_for_status()

    # Process the image
    return process_background_image(img_response.content, size)


def fetch_pexels_image(query: str, size: tuple = (1080, 1080)) -> bytes:
    """
    Fetch a high-quality image from Pexels API.
    Free tier: 200 requests/month.
    """
    if not Config.PEXELS_API_KEY:
        raise ValueError("PEXELS_API_KEY not configured")

    search_url = "https://api.pexels.com/v1/search"
    params = {
        "query": query,
        "per_page": 10,
        "orientation": "square",
    }
    headers = {
        "Authorization": Config.PEXELS_API_KEY
    }

    response = requests.get(search_url, params=params, headers=headers, timeout=15)
    response.raise_for_status()

    photos = response.json().get("photos", [])
    if not photos:
        raise ValueError(f"No images found for query: {query}")

    # Pick a random image from results
    photo = random.choice(photos[:5])
    image_url = photo["src"]["large"]  # 940px width

    # Download the image
    img_response = requests.get(image_url, timeout=30)
    img_response.raise_for_status()

    # Process the image
    return process_background_image(img_response.content, size)


def process_background_image(img_bytes: bytes, size: tuple = (1080, 1080), apply_effects: bool = False) -> bytes:
    """
    Process an image for use as a slide background:
    - Resize/crop to square
    - Optionally apply blur and darkening (disabled by default for crisp look)
    """
    img = Image.open(io.BytesIO(img_bytes))

    # Convert to RGB if necessary
    if img.mode != "RGB":
        img = img.convert("RGB")

    # Crop to square (center crop)
    width, height = img.size
    min_dim = min(width, height)
    left = (width - min_dim) // 2
    top = (height - min_dim) // 2
    img = img.crop((left, top, left + min_dim, top + min_dim))

    # Resize to target size
    img = img.resize(size, Image.Resampling.LANCZOS)

    # Only apply effects if explicitly requested (keeping images crisp by default)
    if apply_effects:
        img = img.filter(ImageFilter.GaussianBlur(radius=2))
        enhancer = ImageEnhance.Brightness(img)
        img = enhancer.enhance(0.6)
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(1.1)

    buf = io.BytesIO()
    img.save(buf, format="PNG", quality=95)
    return buf.getvalue()


def generate_image_azure(prompt: str, size: str = "1024x1024") -> bytes:
    """Generate an image using Azure OpenAI gpt-image-1 and return raw bytes."""
    client = AzureOpenAI(
        api_key=Config.AZURE_OPENAI_API_KEY,
        azure_endpoint=Config.AZURE_OPENAI_ENDPOINT,
        api_version=Config.AZURE_OPENAI_API_VERSION,
    )

    response = client.images.generate(
        model=Config.AZURE_OPENAI_IMAGE_DEPLOYMENT,
        prompt=f"Professional, aesthetic photograph for social media. {prompt}. "
               f"High quality, Instagram-worthy, modern aesthetic. "
               f"Suitable as a background with text overlay.",
        size=size,
        quality="standard",
        n=1,
        output_format="png",
    )

    b64_data = response.data[0].b64_json
    img_bytes = base64.b64decode(b64_data)

    # Process for better text overlay
    return process_background_image(img_bytes)


def generate_image_stability(prompt: str) -> bytes:
    """Generate an image using Stability AI and return raw bytes."""
    url = "https://api.stability.ai/v1/generation/stable-diffusion-xl-1024-v1-0/text-to-image"

    headers = {
        "Authorization": f"Bearer {Config.STABILITY_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "image/png"
    }

    payload = {
        "text_prompts": [
            {
                "text": f"Professional photograph, aesthetic, Instagram-worthy. {prompt}. "
                        f"High quality, modern, suitable for social media carousel.",
                "weight": 1
            },
            {
                "text": "text, letters, words, watermark, signature, ugly, blurry",
                "weight": -1
            }
        ],
        "width": 1024,
        "height": 1024,
        "steps": 30,
        "cfg_scale": 7
    }

    response = requests.post(url, headers=headers, json=payload, timeout=60)
    response.raise_for_status()

    # Process for better text overlay
    return process_background_image(response.content)


def generate_background(
    prompt: str = None,
    theme: str = None,
    save_path: Path = None,
    use_stock: bool = True,
) -> bytes:
    """
    Generate a background image using the configured provider.

    Priority:
    1. Unsplash (if configured) - aesthetic stock photos
    2. Pexels (if configured) - aesthetic stock photos
    3. Azure OpenAI (if configured) - AI generated
    4. Stability AI (if configured) - AI generated
    5. Gradient fallback

    Args:
        prompt: Image generation prompt or search query hint
        theme: Content theme for better search queries
        save_path: Optional path to save the image
        use_stock: Whether to try stock photo APIs first
    """
    img_bytes = None
    search_query = get_search_query(theme, prompt)

    # Force gradient if configured
    if Config.IMAGE_PROVIDER == "gradient":
        img_bytes = generate_fallback_gradient()

    # Try stock photos first (most aesthetic, free)
    elif use_stock:
        # Try Unsplash
        if not img_bytes and Config.UNSPLASH_ACCESS_KEY:
            try:
                img_bytes = fetch_unsplash_image(search_query)
            except Exception as e:
                print(f"  ⚠ Unsplash failed: {e}")

        # Try Pexels
        if not img_bytes and Config.PEXELS_API_KEY:
            try:
                img_bytes = fetch_pexels_image(search_query)
            except Exception as e:
                print(f"  ⚠ Pexels failed: {e}")

    # Try AI generation
    if not img_bytes and Config.IMAGE_PROVIDER == "azure" and Config.AZURE_OPENAI_API_KEY:
        try:
            img_bytes = generate_image_azure(prompt or search_query)
        except Exception as e:
            print(f"  ⚠ Azure AI image failed: {e}")

    if not img_bytes and Config.IMAGE_PROVIDER == "stability" and Config.STABILITY_API_KEY:
        try:
            img_bytes = generate_image_stability(prompt or search_query)
        except Exception as e:
            print(f"  ⚠ Stability AI failed: {e}")

    # Fallback to gradient
    if not img_bytes:
        img_bytes = generate_fallback_gradient()

    if save_path:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_bytes(img_bytes)

    return img_bytes


def generate_fallback_gradient() -> bytes:
    """
    Generate a premium gradient background without any API.
    Used as fallback when no image API is available.
    """
    from PIL import Image, ImageDraw
    import math

    width, height = 1080, 1080

    # Premium color palettes (more aesthetic)
    palettes = [
        # Sunset vibes
        [(25, 25, 112), (255, 99, 71), (255, 165, 0)],
        # Ocean depth
        [(0, 31, 63), (0, 116, 217), (127, 219, 255)],
        # Forest morning
        [(22, 33, 62), (52, 73, 94), (46, 204, 113)],
        # Purple haze
        [(44, 62, 80), (142, 68, 173), (241, 196, 15)],
        # Midnight city
        [(15, 12, 41), (48, 43, 99), (36, 188, 168)],
        # Warm coffee
        [(62, 39, 35), (141, 85, 36), (233, 196, 106)],
        # Cool professional
        [(17, 24, 39), (31, 41, 55), (59, 130, 246)],
        # Rose gold
        [(45, 27, 37), (183, 110, 121), (244, 194, 194)],
    ]

    colors = random.choice(palettes)
    img = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(img)

    # Create smooth multi-color gradient
    for y in range(height):
        for x in range(width):
            # Diagonal gradient with smooth transitions
            ratio = (x / width * 0.6 + y / height * 0.4)

            if len(colors) == 2:
                r = int(colors[0][0] + (colors[1][0] - colors[0][0]) * ratio)
                g = int(colors[0][1] + (colors[1][1] - colors[0][1]) * ratio)
                b = int(colors[0][2] + (colors[1][2] - colors[0][2]) * ratio)
            else:
                # Three color gradient
                if ratio < 0.5:
                    sub_ratio = ratio * 2
                    r = int(colors[0][0] + (colors[1][0] - colors[0][0]) * sub_ratio)
                    g = int(colors[0][1] + (colors[1][1] - colors[0][1]) * sub_ratio)
                    b = int(colors[0][2] + (colors[1][2] - colors[0][2]) * sub_ratio)
                else:
                    sub_ratio = (ratio - 0.5) * 2
                    r = int(colors[1][0] + (colors[2][0] - colors[1][0]) * sub_ratio)
                    g = int(colors[1][1] + (colors[2][1] - colors[1][1]) * sub_ratio)
                    b = int(colors[1][2] + (colors[2][2] - colors[1][2]) * sub_ratio)

            draw.point((x, y), fill=(r, g, b))

    # Add subtle noise for texture
    import random as rnd
    for _ in range(5000):
        x = rnd.randint(0, width - 1)
        y = rnd.randint(0, height - 1)
        current = img.getpixel((x, y))
        noise = rnd.randint(-10, 10)
        new_color = tuple(max(0, min(255, c + noise)) for c in current)
        draw.point((x, y), fill=new_color)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


if __name__ == "__main__":
    # Test image generation
    print("Testing image generation...")

    # Test gradient
    gradient_bytes = generate_fallback_gradient()
    print(f"Gradient: {len(gradient_bytes)} bytes")

    # Test with theme
    if Config.UNSPLASH_ACCESS_KEY:
        try:
            unsplash_bytes = fetch_unsplash_image("professional office")
            print(f"Unsplash: {len(unsplash_bytes)} bytes")
        except Exception as e:
            print(f"Unsplash error: {e}")

    # Test generate_background
    bg_bytes = generate_background(theme="interview")
    print(f"Background: {len(bg_bytes)} bytes")
