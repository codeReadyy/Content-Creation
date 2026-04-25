"""
AI image generation for slide backgrounds.
Supports Azure OpenAI DALL-E 3, Stability AI, and local gradient fallback.
"""

import io
import requests
from pathlib import Path
from openai import AzureOpenAI
from config.settings import Config


def generate_image_azure(prompt: str, size: str = "1024x1024") -> bytes:
    """Generate an image using Azure OpenAI DALL-E 3 and return raw bytes."""
    client = AzureOpenAI(
        api_key=Config.AZURE_OPENAI_API_KEY,
        azure_endpoint=Config.AZURE_OPENAI_ENDPOINT,
        api_version=Config.AZURE_OPENAI_API_VERSION,
    )

    response = client.images.generate(
        model=Config.AZURE_OPENAI_DALLE_DEPLOYMENT,
        prompt=f"Abstract, clean, modern background for a social media slide. {prompt}. "
               f"No text, no words, no letters. Minimalist, professional, atmospheric. "
               f"Suitable as a background with text overlay. High contrast edges.",
        size=size,
        quality="standard",
        n=1,
    )

    image_url = response.data[0].url
    img_response = requests.get(image_url, timeout=30)
    img_response.raise_for_status()
    return img_response.content


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
                "text": f"Abstract, clean, modern background. {prompt}. "
                        f"No text, no words. Minimalist, professional.",
                "weight": 1
            },
            {
                "text": "text, letters, words, watermark, signature",
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
    return response.content


def generate_background(prompt: str, save_path: Path = None) -> bytes:
    """
    Generate a background image using the configured provider.
    Falls back to gradient if API calls fail.
    Optionally save to disk.
    """
    img_bytes = None

    if Config.IMAGE_PROVIDER == "gradient":
        img_bytes = generate_fallback_gradient()
    elif Config.IMAGE_PROVIDER == "stability" and Config.STABILITY_API_KEY:
        img_bytes = generate_image_stability(prompt)
    elif Config.IMAGE_PROVIDER == "azure" and Config.AZURE_OPENAI_API_KEY:
        img_bytes = generate_image_azure(prompt)
    else:
        # No valid provider configured, use gradient
        img_bytes = generate_fallback_gradient()

    if save_path:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_bytes(img_bytes)

    return img_bytes


def generate_fallback_gradient() -> bytes:
    """
    Generate a simple gradient background without any API.
    Used as fallback when no image API is available, or when IMAGE_PROVIDER=gradient.
    """
    from PIL import Image, ImageDraw
    import random

    width, height = 1080, 1080

    # Color palettes for gradients
    palettes = [
        [(15, 23, 42), (59, 130, 246)],      # Dark navy -> Blue
        [(17, 24, 39), (139, 92, 246)],       # Dark -> Purple
        [(7, 89, 133), (14, 165, 233)],       # Teal -> Sky
        [(30, 41, 59), (248, 113, 113)],      # Slate -> Coral
        [(17, 24, 39), (52, 211, 153)],       # Dark -> Emerald
        [(55, 48, 107), (236, 72, 153)],      # Indigo -> Pink
        [(28, 25, 23), (234, 179, 8)],        # Almost black -> Amber
    ]

    colors = random.choice(palettes)
    img = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(img)

    # Diagonal gradient
    for y in range(height):
        for x in range(width):
            ratio = (x / width * 0.5 + y / height * 0.5)
            r = int(colors[0][0] + (colors[1][0] - colors[0][0]) * ratio)
            g = int(colors[0][1] + (colors[1][1] - colors[0][1]) * ratio)
            b = int(colors[0][2] + (colors[1][2] - colors[0][2]) * ratio)
            draw.point((x, y), fill=(r, g, b))

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
