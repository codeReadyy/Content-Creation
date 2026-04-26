"""
Telegram notifier — sends pipeline status updates to your Telegram.

Setup:
1. Message @BotFather on Telegram
2. Send /newbot and follow instructions to create a bot
3. Copy the bot token (looks like: 123456789:ABCdefGHIjklMNOpqrsTUVwxyz)
4. Message your new bot (just say "hi")
5. Get your chat ID: https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
   Look for "chat":{"id":123456789} — that number is your chat ID
6. Add to GitHub secrets:
   - TELEGRAM_BOT_TOKEN: your bot token
   - TELEGRAM_CHAT_ID: your chat ID
"""

import requests
from config.settings import Config

# Get from environment
TELEGRAM_BOT_TOKEN = getattr(Config, 'TELEGRAM_BOT_TOKEN', '') or ''
TELEGRAM_CHAT_ID = getattr(Config, 'TELEGRAM_CHAT_ID', '') or ''


def send_telegram_message(message: str, parse_mode: str = "HTML") -> dict:
    """
    Send a message to Telegram.

    Args:
        message: The message text (supports HTML formatting)
        parse_mode: "HTML" or "Markdown"

    Returns:
        Dict with result or error
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return {"error": "Telegram not configured (missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID)"}

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True
    }

    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        return {"status": "sent"}
    except Exception as e:
        print(f"  ⚠️ Telegram notification failed: {e}")
        return {"error": str(e)}


def notify_pipeline_result(results: dict) -> dict:
    """
    Send a formatted pipeline status notification.

    Args:
        results: The pipeline results dict from main.py
    """
    date = results.get("date", "Unknown")
    stages = results.get("stages", {})

    # Determine overall status
    has_errors = any("error" in str(v).lower() for v in stages.values())

    if has_errors:
        status_emoji = "❌"
        status_text = "FAILED"
    else:
        status_emoji = "✅"
        status_text = "SUCCESS"

    # Build message
    lines = [
        f"{status_emoji} <b>AssuredReferral AutoPoster</b>",
        f"📅 {date}",
        f"Status: <b>{status_text}</b>",
        "",
        "<b>Pipeline Stages:</b>"
    ]

    stage_emojis = {
        "research": "🔍",
        "synthesis": "🧠",
        "content_generation": "📝",
        "slide_generation": "🎨",
        "video_generation": "🎬",
        "linkedin": "💼",
        "youtube": "📺",
        "instagram": "📸",
        "publishing": "📤"
    }

    for stage, result in stages.items():
        emoji = stage_emojis.get(stage, "•")
        result_str = str(result)

        if "success" in result_str.lower():
            stage_status = "✓"
        elif "error" in result_str.lower():
            stage_status = "✗"
        elif "skipped" in result_str.lower():
            stage_status = "○"
        else:
            stage_status = "•"

        # Truncate long error messages
        if len(result_str) > 50:
            result_str = result_str[:47] + "..."

        lines.append(f"{emoji} {stage}: {stage_status} {result_str}")

    # Add links if available
    if results.get("slide_paths"):
        lines.append(f"\n📊 Slides: {len(results['slide_paths'])} generated")

    if results.get("video_path"):
        lines.append("🎥 Video: Generated")

    if results.get("pdf_path"):
        lines.append("📄 PDF: Generated")

    # Add LinkedIn post link if available
    linkedin_result = stages.get("linkedin", {})
    if isinstance(linkedin_result, dict) and linkedin_result.get("post_urn"):
        lines.append(f"\n🔗 <a href='https://www.linkedin.com/feed/update/{linkedin_result['post_urn']}'>View LinkedIn Post</a>")

    message = "\n".join(lines)
    return send_telegram_message(message)


def notify_error(error: str, stage: str = "Unknown") -> dict:
    """Send an error notification."""
    message = f"""❌ <b>Pipeline Error</b>

Stage: {stage}
Error: <code>{error[:500]}</code>

Check GitHub Actions for details."""

    return send_telegram_message(message)


def notify_success_simple(linkedin_posted: bool = False, youtube_posted: bool = False) -> dict:
    """Send a simple success notification."""
    lines = ["✅ <b>Daily Post Complete!</b>", ""]

    if linkedin_posted:
        lines.append("💼 LinkedIn: Posted")
    if youtube_posted:
        lines.append("📺 YouTube: Uploaded")

    if not linkedin_posted and not youtube_posted:
        lines.append("📁 Content generated (dry run)")

    return send_telegram_message("\n".join(lines))


if __name__ == "__main__":
    # Test the notifier
    print("Testing Telegram Notifier...")
    print(f"Bot Token: {'Set' if TELEGRAM_BOT_TOKEN else 'NOT SET'}")
    print(f"Chat ID: {'Set' if TELEGRAM_CHAT_ID else 'NOT SET'}")

    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        result = send_telegram_message("🧪 <b>Test message</b>\n\nYour AssuredReferral AutoPoster notifications are working!")
        print(f"Result: {result}")
    else:
        print("\nTo test, set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in your .env file")
