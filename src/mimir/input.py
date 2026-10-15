from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from mimir.models import InputEnvelope

URL_PATTERN = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)
SIMPLIFIED_HINTS = set("这发为国体会与云后里来时个门开关学网应从书车马见长东业")
TRADITIONAL_HINTS = set("這發為國體會與雲後裡來時個門開關學網應從書車馬見長東業")


def detect_language(text: str) -> str:
    has_ascii = bool(re.search(r"[A-Za-z]", text))
    simplified = sum(char in SIMPLIFIED_HINTS for char in text)
    traditional = sum(char in TRADITIONAL_HINTS for char in text)
    has_han = bool(re.search(r"[\u3400-\u9fff]", text))
    if has_han and has_ascii:
        return "mixed"
    if simplified > traditional:
        return "zh-Hans"
    if has_han:
        return "zh-Hant"
    if has_ascii:
        return "en"
    return "und"


def _received_at(message: dict[str, Any]) -> str:
    timestamp = message.get("date")
    if isinstance(timestamp, int) and timestamp >= 0:
        return datetime.fromtimestamp(timestamp, tz=UTC).isoformat()
    return datetime.now(UTC).isoformat()


def normalize_update(update: dict[str, Any], owner_user_id: int) -> InputEnvelope | None:
    update_id = update.get("update_id")
    message = update.get("message")
    if not isinstance(update_id, int) or not isinstance(message, dict):
        return None

    sender = message.get("from") or {}
    chat = message.get("chat") or {}
    user_id = sender.get("id")
    chat_id = chat.get("id")
    if user_id != owner_user_id or chat.get("type") != "private" or not isinstance(chat_id, int):
        return None

    caption = message.get("caption") if isinstance(message.get("caption"), str) else ""
    text = message.get("text") if isinstance(message.get("text"), str) else ""
    photos = message.get("photo")

    if isinstance(photos, list) and photos:
        largest = photos[-1] if isinstance(photos[-1], dict) else {}
        file_id = largest.get("file_id")
        if isinstance(file_id, str) and file_id:
            visible = caption.strip()
            return InputEnvelope(
                update_id=update_id,
                user_id=user_id,
                chat_id=chat_id,
                input_type="image",
                original_text=visible,
                original_url=None,
                telegram_file_id=file_id,
                telegram_file_unique_id=largest.get("file_unique_id"),
                detected_language=detect_language(visible),
                received_at=_received_at(message),
            )

    visible = text.strip()
    urls = [match.rstrip(".,;:!?)]}") for match in URL_PATTERN.findall(visible)]
    if visible and urls:
        input_type = "url"
        original_url = urls[0]
    elif visible:
        input_type = "text"
        original_url = None
    else:
        input_type = "unsupported"
        original_url = None

    return InputEnvelope(
        update_id=update_id,
        user_id=user_id,
        chat_id=chat_id,
        input_type=input_type,
        original_text=visible,
        original_url=original_url,
        telegram_file_id=None,
        telegram_file_unique_id=None,
        detected_language=detect_language(visible),
        received_at=_received_at(message),
    )
