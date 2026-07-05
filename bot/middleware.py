"""Access-control and busy-chat middlewares."""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, Optional

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


class BusyGuardMiddleware(BaseMiddleware):
    """Blocks new messages/callbacks in a chat while a test-solving job is running there."""

    def __init__(self, is_busy: Callable[[int], Optional[str]]) -> None:
        self.is_busy = is_busy

    async def __call__(
        self,
        handler: Callable[[Any, Dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: Dict[str, Any],
    ) -> Any:
        chat = data.get("event_chat")
        label = self.is_busy(chat.id) if chat is not None else None
        if label is not None:
            if hasattr(event, "answer"):
                await event.answer(
                    f"⏳ Hozircha band: {label} jarayoni tugashini kuting."
                )
            return None
        return await handler(event, data)
