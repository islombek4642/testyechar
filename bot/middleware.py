"""Access-control and busy-chat middlewares."""
from __future__ import annotations

import time
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
    """Blocks new messages/callbacks in a chat while a test-solving job is running there.

    Notifies the user at most once per notify_interval seconds per chat —
    without this, an impatient user tapping/sending repeatedly during a
    long wait would get a fresh "band" reply for every single tap, which
    both spams the chat and pushes the eventual result message further and
    further behind, out of easy view.
    """

    def __init__(
        self, is_busy: Callable[[int], Optional[str]], notify_interval: float = 20.0
    ) -> None:
        self.is_busy = is_busy
        self.notify_interval = notify_interval
        self._last_notified: Dict[int, Optional[float]] = {}

    async def __call__(
        self,
        handler: Callable[[Any, Dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: Dict[str, Any],
    ) -> Any:
        chat = data.get("event_chat")
        label = self.is_busy(chat.id) if chat is not None else None
        if label is not None:
            now = time.monotonic()
            last = self._last_notified.get(chat.id)
            if last is None or now - last >= self.notify_interval:
                self._last_notified[chat.id] = now
                if hasattr(event, "answer"):
                    await event.answer(
                        f"⏳ Hozircha {label} davom etmoqda — birozdan keyin qayta urinib ko'ring."
                    )
            return None
        return await handler(event, data)
