"""notify_telegram.py — the human-in-the-loop approval channel for NinniTales.

Reuses the SAME bot you already use for AssuredReferral (TELEGRAM_BOT_TOKEN +
TELEGRAM_CHAT_ID). Two directions:

  daily.py        → send_video_preview(): pushes the freshly built Short to your
                    chat with a ❌ Cancel button, so you can veto before it goes live.
  telegram_poll.py→ get_updates() / answer_callback(): reads your taps and acts.

Veto model: the Short is ALREADY scheduled on YouTube when the preview arrives. Do
nothing and it publishes at 7pm ET; tap ❌ and telegram_poll deletes it.
"""

import os

import requests

API = "https://api.telegram.org/bot{token}/{method}"


def _cfg() -> tuple[str | None, str | None]:
    return os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")


def configured() -> bool:
    token, chat = _cfg()
    return bool(token and chat)


def _call(method: str, *, files=None, **data) -> dict:
    token, _ = _cfg()
    if not token:
        return {"error": "TELEGRAM_BOT_TOKEN not set"}
    try:
        r = requests.post(API.format(token=token, method=method),
                          data=data, files=files, timeout=60)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"  ⚠️  telegram {method} failed: {e}")
        return {"error": str(e)}


def send_message(text: str) -> dict:
    _, chat = _cfg()
    return _call("sendMessage", chat_id=chat, text=text, parse_mode="HTML",
                 disable_web_page_preview="true")


def send_video_preview(video_path: str, caption: str, veto_token: str) -> dict:
    """Upload the Short to the chat with Cancel / Cancel-&-make-another buttons.

    `veto_token` (the video_id) is echoed back in each button's callback_data so
    telegram_poll knows which scheduled video the tap refers to:
      "veto:<video_id>"  → delete it, post nothing
      "regen:<video_id>" → delete it AND build a fresh replacement
    """
    _, chat = _cfg()
    keyboard = {"inline_keyboard": [[
        {"text": "❌ Cancel", "callback_data": f"veto:{veto_token}"},
        {"text": "🔄 Cancel & make another", "callback_data": f"regen:{veto_token}"},
    ]]}
    import json
    with open(video_path, "rb") as fh:
        return _call("sendVideo", files={"video": fh},
                     chat_id=chat, caption=caption, parse_mode="HTML",
                     reply_markup=json.dumps(keyboard))


def get_updates(offset: int | None = None, timeout: int = 0) -> list[dict]:
    """Long-poll-ish fetch of new updates. Pass the last handled update_id + 1."""
    params = {"timeout": timeout, "allowed_updates": '["callback_query"]'}
    if offset is not None:
        params["offset"] = offset
    res = _call("getUpdates", **params)
    return res.get("result", []) if "error" not in res else []


def answer_callback(callback_query_id: str, text: str = "") -> dict:
    """Stop the button's spinner and optionally show a toast to the user."""
    return _call("answerCallbackQuery", callback_query_id=callback_query_id,
                 text=text)


if __name__ == "__main__":
    print("Telegram configured:", configured())
    if configured():
        print(send_message("🧪 <b>NinniTales</b> approval channel is live."))
