"""Bot configuration loaded from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass

CLAUDE_MODEL = "claude-opus-4-8"


@dataclass(frozen=True)
class BotSettings:
    bot_token: str
    admin_id: int
    allowed_users: frozenset
    anthropic_api_key: str
    model: str = CLAUDE_MODEL

    def is_allowed(self, user_id: int) -> bool:
        return user_id == self.admin_id or user_id in self.allowed_users


def load_settings() -> BotSettings:
    token = os.environ.get("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN muhit o'zgaruvchisi o'rnatilmagan")

    admin_raw = os.environ.get("BOT_ADMIN_ID", "").strip()
    if not admin_raw.isdigit():
        raise RuntimeError("BOT_ADMIN_ID raqamli Telegram user ID bo'lishi kerak")

    allowed = frozenset(
        int(part.strip())
        for part in os.environ.get("BOT_ALLOWED_USERS", "").split(",")
        if part.strip().isdigit()
    )

    # Ixtiyoriy: kalit bo'lmasa ham bot ishlaydi (Parser rejimi kalitsiz),
    # AI Resolver handleri ishlatishdan oldin o'zi tekshiradi.
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()

    return BotSettings(
        bot_token=token,
        admin_id=int(admin_raw),
        allowed_users=allowed,
        anthropic_api_key=api_key,
    )
