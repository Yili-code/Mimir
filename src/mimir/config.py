from __future__ import annotations

import os
from dataclasses import dataclass

from mimir.errors import ConfigurationError


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigurationError(f"Missing required environment variable: {name}")
    return value


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ConfigurationError(f"{name} must be between {minimum} and {maximum}")
    return value


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    telegram_owner_user_id: int
    gemini_api_key: str
    google_cloud_project: str
    owner_profile: str
    owner_profile_version: str = "owner-v1"
    firestore_database: str = "(default)"
    gemini_model: str = "gemini-3.8-flash"
    max_cases_per_run: int = 5
    max_claims: int = 5
    max_sources: int = 8
    max_image_bytes: int = 10 * 1024 * 1024
    max_page_bytes: int = 2 * 1024 * 1024
    max_extracted_chars: int = 20_000
    max_failure_attempts: int = 4
    lease_seconds: int = 15 * 60

    @classmethod
    def from_env(cls) -> Settings:
        try:
            owner_id = int(_required("TELEGRAM_OWNER_USER_ID"))
        except ValueError as exc:
            raise ConfigurationError("TELEGRAM_OWNER_USER_ID must be an integer") from exc

        return cls(
            telegram_bot_token=_required("TELEGRAM_BOT_TOKEN"),
            telegram_owner_user_id=owner_id,
            gemini_api_key=_required("GEMINI_API_KEY"),
            google_cloud_project=_required("GOOGLE_CLOUD_PROJECT"),
            owner_profile=_required("MIMIR_OWNER_PROFILE"),
            owner_profile_version=os.getenv("MIMIR_OWNER_PROFILE_VERSION", "owner-v1").strip()
            or "owner-v1",
            firestore_database=os.getenv("FIRESTORE_DATABASE", "(default)").strip() or "(default)",
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip()
            or "gemini-3.8-flash",
            max_cases_per_run=_bounded_int("MIMIR_MAX_CASES_PER_RUN", 5, 1, 20),
            max_claims=_bounded_int("MIMIR_MAX_CLAIMS", 5, 1, 8),
            max_sources=_bounded_int("MIMIR_MAX_SOURCES", 8, 1, 12),
            max_failure_attempts=_bounded_int("MIMIR_MAX_FAILURE_ATTEMPTS", 4, 1, 10),
        )
