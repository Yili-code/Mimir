from __future__ import annotations

import json
import logging

from mimir.config import Settings
from mimir.errors import MimirError
from mimir.gemini import GeminiClient
from mimir.repository import FirestoreRepository
from mimir.service import MimirService
from mimir.telegram import TelegramClient
from mimir.url_fetcher import SafeURLFetcher

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
LOGGER = logging.getLogger("mimir")


def build_service(settings: Settings) -> MimirService:
    return MimirService(
        settings=settings,
        repository=FirestoreRepository(
            project=settings.google_cloud_project,
            database=settings.firestore_database,
        ),
        telegram=TelegramClient(settings.telegram_bot_token),
        gemini=GeminiClient(settings.gemini_api_key, settings.gemini_model),
        url_fetcher=SafeURLFetcher(
            max_bytes=settings.max_page_bytes,
            max_chars=settings.max_extracted_chars,
        ),
    )


def main() -> int:
    try:
        settings = Settings.from_env()
        report = build_service(settings).run_once()
    except MimirError as exc:
        LOGGER.error("Mimir run failed: %s", type(exc).__name__)
        return 1
    except Exception as exc:  # unexpected failures must fail the workflow without leaking content
        LOGGER.exception("Unexpected Mimir failure: %s", type(exc).__name__)
        return 1
    LOGGER.info("Mimir run completed: %s", json.dumps(report.to_dict(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
