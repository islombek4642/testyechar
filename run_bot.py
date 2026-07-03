"""One-command launcher: loads .env, ensures dirs, starts polling."""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from app.config import settings

settings.ensure_dirs()

from app.utils.logger import setup_logging

setup_logging(log_level="INFO", log_file=settings.logs_dir / "bot.log")

from bot.main import main

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Bot to'xtatildi.")
