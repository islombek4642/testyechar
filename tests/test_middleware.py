import asyncio
from types import SimpleNamespace

from bot.middleware import AccessMiddleware, BusyGuardMiddleware


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


def test_busy_guard_blocks_when_chat_is_busy():
    mw = BusyGuardMiddleware(is_busy=lambda chat_id: "Parser" if chat_id == 42 else None)
    event, called = FakeEvent(), {}

    async def handler(e, d):
        called["yes"] = True

    asyncio.run(mw(handler, event, {"event_chat": SimpleNamespace(id=42)}))
    assert "yes" not in called
    assert event.replies
    assert "Parser" in event.replies[0]


def test_busy_guard_passes_through_when_not_busy():
    mw = BusyGuardMiddleware(is_busy=lambda chat_id: None)
    event, called = FakeEvent(), {}

    async def handler(e, d):
        called["yes"] = True

    asyncio.run(mw(handler, event, {"event_chat": SimpleNamespace(id=42)}))
    assert called.get("yes")
    assert not event.replies


def test_busy_guard_notifies_once_then_throttles_until_interval_passes(monkeypatch):
    import bot.middleware as middleware_module

    fake_now = {"t": 0.0}
    monkeypatch.setattr(middleware_module.time, "monotonic", lambda: fake_now["t"])

    mw = BusyGuardMiddleware(is_busy=lambda chat_id: "Tahlil", notify_interval=20.0)
    event = FakeEvent()
    data = {"event_chat": SimpleNamespace(id=42)}

    async def handler(e, d):
        pass

    asyncio.run(mw(handler, event, data))
    assert len(event.replies) == 1

    fake_now["t"] = 5.0  # still inside the throttle window
    asyncio.run(mw(handler, event, data))
    assert len(event.replies) == 1  # no repeat notification yet

    fake_now["t"] = 25.0  # window has passed
    asyncio.run(mw(handler, event, data))
    assert len(event.replies) == 2
