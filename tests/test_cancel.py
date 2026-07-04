import asyncio

from bot.handlers import BTN_CANCEL, CANCEL_KB, MAIN_KB, cancel_waiting, choose_parser
from bot.states import Mode


class FakeState:
    def __init__(self):
        self.cleared = False
        self.set_to = None

    async def clear(self):
        self.cleared = True

    async def set_state(self, state):
        self.set_to = state


class FakeMessage:
    def __init__(self):
        self.answers = []

    async def answer(self, text, **kwargs):
        self.answers.append((text, kwargs.get("reply_markup")))


def test_cancel_keyboard_has_single_button():
    buttons = CANCEL_KB.keyboard[0]
    assert [b.text for b in buttons] == [BTN_CANCEL]


def test_choose_parser_shows_cancel_keyboard():
    message, state = FakeMessage(), FakeState()
    asyncio.run(choose_parser(message, state))
    assert state.set_to == Mode.parser_waiting
    _, markup = message.answers[0]
    assert markup is CANCEL_KB


def test_cancel_waiting_clears_state_and_restores_main_keyboard():
    message, state = FakeMessage(), FakeState()
    asyncio.run(cancel_waiting(message, state))
    assert state.cleared
    text, markup = message.answers[0]
    assert markup is MAIN_KB
    assert "Bekor qilindi" in text
