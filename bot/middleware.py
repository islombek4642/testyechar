"""Access-control middleware: only allowed Telegram user IDs may use the bot."""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware

DENIED_TEXT = "⛔ Kechirasiz, sizga bu botdan foydalanishga ruxsat berilmagan."


class AccessMiddleware(BaseMiddleware):
    def __init__(self, settings) -> None:
        self.settings = settings

    async def __call__(
        self,
        handler: Callable[[Any, Dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: Dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None or not self.settings.is_allowed(user.id):
            if hasattr(event, "answer"):
                await event.answer(DENIED_TEXT)
            return None
        return await handler(event, data)
