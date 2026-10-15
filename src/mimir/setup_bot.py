from __future__ import annotations

import argparse
import os

from mimir.errors import ConfigurationError
from mimir.telegram import TelegramClient


def main() -> int:
    parser = argparse.ArgumentParser(description="Switch the dedicated Mimir bot to polling mode")
    parser.add_argument(
        "--drop-pending-updates",
        action="store_true",
        help="Discard Telegram updates queued before setup",
    )
    args = parser.parse_args()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise ConfigurationError("Missing required environment variable: TELEGRAM_BOT_TOKEN")
    TelegramClient(token).delete_webhook(drop_pending_updates=args.drop_pending_updates)
    print("Mimir bot is ready for getUpdates polling.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
