import asyncio
from types import SimpleNamespace

from bot.middleware import AccessMiddleware


class FakeEvent:
    def __init__(self):
        self.replies = []

    async def answer(self, text, **kwargs):
        self.replies.append(text)


def _settings(allowed_id: int):
    return SimpleNamespace(is_allowed=lambda uid: uid == allowed_id)


def test_blocks_unknown_user():
    mw = AccessMiddleware(_settings(allowed_id=1))
    event, called = FakeEvent(), {}

    async def handler(e, d):
        called["yes"] = True

    asyncio.run(mw(handler, event, {"event_from_user": SimpleNamespace(id=99)}))
    assert "yes" not in called
    assert event.replies  # refusal message sent


def test_allows_known_user():
    mw = AccessMiddleware(_settings(allowed_id=1))
    event, called = FakeEvent(), {}

    async def handler(e, d):
        called["yes"] = True

    asyncio.run(mw(handler, event, {"event_from_user": SimpleNamespace(id=1)}))
    assert called.get("yes")
    assert not event.replies
