from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

InputType = Literal["text", "url", "image", "unsupported"]


@dataclass(frozen=True)
class InputEnvelope:
    update_id: int
    user_id: int
    chat_id: int
    input_type: InputType
    original_text: str
    original_url: str | None
    telegram_file_id: str | None
    telegram_file_unique_id: str | None
    detected_language: str
    received_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PollState:
    initialized: bool
    last_update_id: int | None


@dataclass(frozen=True)
class RunReport:
    baselined: bool = False
    received: int = 0
    processed: int = 0
    delivered: int = 0
    retryable_failures: int = 0
    terminal_failures: int = 0

    def to_dict(self) -> dict[str, int | bool]:
        return asdict(self)
