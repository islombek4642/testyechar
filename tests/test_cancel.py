import asyncio

from bot.handlers import (
    BTN_CANCEL,
    CANCEL_KB,
    MAIN_KB_ADMIN,
    MAIN_KB_USER,
    cancel_waiting,
    choose_parser,
)
from bot.states import Mode


class FakeState:
    def __init__(self):
        self.cleared = False
        self.set_to = None

    async def clear(self):
        self.cleared = True

    async def set_state(self, state):
        self.set_to = state


class FakeUser:
    def __init__(self, id):
        self.id = id


class FakeMessage:
    def __init__(self, user_id=1):
        self.from_user = FakeUser(user_id)
        self.answers = []

    async def answer(self, text, **kwargs):
        self.answers.append((text, kwargs.get("reply_markup")))


class FakeSettings:
    def __init__(self, admin_id=1):
        self.admin_id = admin_id


def test_cancel_keyboard_has_single_button():
    buttons = CANCEL_KB.keyboard[0]
    assert [b.text for b in buttons] == [BTN_CANCEL]


def test_choose_parser_shows_cancel_keyboard():
    message, state = FakeMessage(), FakeState()
    asyncio.run(choose_parser(message, state))
    assert state.set_to == Mode.parser_waiting
    _, markup = message.answers[0]
    assert markup is CANCEL_KB


def test_cancel_waiting_restores_admin_menu_for_admin():
    message, state = FakeMessage(user_id=1), FakeState()
    asyncio.run(cancel_waiting(message, state, FakeSettings(admin_id=1)))
    assert state.cleared
    text, markup = message.answers[0]
    assert markup is MAIN_KB_ADMIN
    assert "Bekor qilindi" in text


def test_cancel_waiting_restores_user_menu_for_non_admin():
    message, state = FakeMessage(user_id=999), FakeState()
    asyncio.run(cancel_waiting(message, state, FakeSettings(admin_id=1)))
    assert state.cleared
    _, markup = message.answers[0]
    assert markup is MAIN_KB_USER
