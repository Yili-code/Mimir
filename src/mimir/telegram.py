from __future__ import annotations

import time
from typing import Any

import httpx

from mimir.errors import PermanentError, RetryableError


class TelegramClient:
    def __init__(self, bot_token: str, *, timeout: float = 20.0) -> None:
        self._base_url = f"https://api.telegram.org/bot{bot_token}"
        self._file_base_url = f"https://api.telegram.org/file/bot{bot_token}"
        self._timeout = timeout

    def _call(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = httpx.post(
                f"{self._base_url}/{method}",
                json=payload,
                timeout=self._timeout,
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise RetryableError("TELEGRAM_NETWORK", type(exc).__name__) from exc
        if response.status_code == 429 or response.status_code >= 500:
            raise RetryableError("TELEGRAM_TRANSIENT_HTTP", str(response.status_code))
        if response.status_code >= 400:
            raise PermanentError("TELEGRAM_HTTP", str(response.status_code))
        try:
            data = response.json()
        except ValueError as exc:
            raise RetryableError("TELEGRAM_INVALID_JSON") from exc
        if not data.get("ok"):
            error_code = data.get("error_code")
            if error_code == 429 or (isinstance(error_code, int) and error_code >= 500):
                raise RetryableError("TELEGRAM_API_TRANSIENT", str(error_code))
            raise PermanentError("TELEGRAM_API_REJECTED", str(error_code))
        return data

    def get_updates(self, *, offset: int | None, limit: int = 100) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "limit": limit,
            "timeout": 0,
            "allowed_updates": ["message"],
        }
        if offset is not None:
            payload["offset"] = offset
        result = self._call("getUpdates", payload).get("result", [])
        return result if isinstance(result, list) else []

    def get_webhook_url(self) -> str:
        result = self._call("getWebhookInfo", {}).get("result", {})
        return result.get("url", "") if isinstance(result, dict) else ""

    def delete_webhook(self, *, drop_pending_updates: bool) -> None:
        self._call("deleteWebhook", {"drop_pending_updates": drop_pending_updates})

    def download_file(self, file_id: str, *, max_bytes: int) -> tuple[bytes, str]:
        file_result = self._call("getFile", {"file_id": file_id}).get("result", {})
        file_path = file_result.get("file_path") if isinstance(file_result, dict) else None
        file_size = file_result.get("file_size") if isinstance(file_result, dict) else None
        if isinstance(file_size, int) and file_size > max_bytes:
            raise PermanentError("IMAGE_TOO_LARGE")
        if not isinstance(file_path, str) or not file_path:
            raise PermanentError("TELEGRAM_FILE_PATH_MISSING")
        try:
            response = httpx.get(f"{self._file_base_url}/{file_path}", timeout=self._timeout)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise RetryableError("TELEGRAM_FILE_NETWORK", type(exc).__name__) from exc
        if response.status_code >= 500:
            raise RetryableError("TELEGRAM_FILE_TRANSIENT_HTTP", str(response.status_code))
        if response.status_code >= 400:
            raise PermanentError("TELEGRAM_FILE_HTTP", str(response.status_code))
        if len(response.content) > max_bytes:
            raise PermanentError("IMAGE_TOO_LARGE")
        content_type = response.headers.get("content-type", "image/jpeg").split(";", 1)[0]
        if not content_type.startswith("image/"):
            raise PermanentError("TELEGRAM_FILE_NOT_IMAGE")
        return response.content, content_type

    def send_message(self, chat_id: int, text: str) -> int:
        result = self._call(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
        ).get("result", {})
        message_id = result.get("message_id") if isinstance(result, dict) else None
        if not isinstance(message_id, int):
            raise RetryableError("TELEGRAM_RECEIPT_MISSING")
        return message_id


def wait_for_retry_after(seconds: float) -> None:
    """Small bounded helper for explicit CLI operations, never scheduled polling."""
    time.sleep(min(max(seconds, 0), 10))
