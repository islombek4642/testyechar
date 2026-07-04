import asyncio

from bot.handlers import (
    MODEL_KB,
    MODEL_OPTIONS,
    get_selected_model,
    handle_model_choice,
    show_settings,
)
from bot.states import Mode


class FakeChat:
    def __init__(self, id):
        self.id = id


class FakeSentMessage:
    def __init__(self, message_id):
        self.message_id = message_id


class FakeMessage:
    def __init__(self, chat_id, text=None):
        self.chat = FakeChat(chat_id)
        self.text = text
        self.answers = []
        self._next_msg_id = 1000

    async def answer(self, text, **kwargs):
        self.answers.append((text, kwargs.get("reply_markup")))
        sent = FakeSentMessage(self._next_msg_id)
        self._next_msg_id += 1
        return sent


class FakeState:
    def __init__(self):
        self.cleared = False
        self.set_to = None

    async def clear(self):
        self.cleared = True

    async def set_state(self, state):
        self.set_to = state


class FakeSettings:
    def __init__(self, model):
        self.model = model


class FakeBot:
    def __init__(self):
        self.edits = []  # list of (chat_id, message_id, text)

    async def edit_message_text(self, chat_id, message_id, text, **kwargs):
        self.edits.append((chat_id, message_id, text))


def test_model_options_has_three_models_in_order():
    assert list(MODEL_OPTIONS.keys()) == [
        "claude-opus-4-8",
        "claude-opus-4-7",
        "claude-sonnet-5",
    ]
    assert MODEL_OPTIONS["claude-opus-4-8"] == "Claude Opus 4.8"
    assert MODEL_OPTIONS["claude-opus-4-7"] == "Claude Opus 4.7"
    assert MODEL_OPTIONS["claude-sonnet-5"] == "Claude Sonnet 5"


def test_model_keyboard_has_one_button_per_model():
    texts = [row[0].text for row in MODEL_KB.keyboard]
    assert texts == list(MODEL_OPTIONS.values())


def test_get_selected_model_falls_back_to_default():
    assert get_selected_model(424242, "claude-opus-4-8") == "claude-opus-4-8"


def test_show_settings_switches_state_and_sends_model_keyboard():
    message = FakeMessage(chat_id=111)
    state = FakeState()
    settings = FakeSettings(model="claude-opus-4-8")
    asyncio.run(show_settings(message, state, settings))
    assert state.set_to == Mode.choosing_model
    text, markup = message.answers[0]
    assert "Claude Opus 4.8" in text
    assert markup is MODEL_KB


def test_handle_model_choice_stores_preference_edits_old_message_and_returns_to_menu():
    message = FakeMessage(chat_id=222, text="Claude Opus 4.7")
    state = FakeState()
    bot = FakeBot()
    from bot import handlers

    handlers._settings_msg_id[222] = 555

    asyncio.run(handle_model_choice(message, state, bot))

    assert get_selected_model(222, "claude-opus-4-8") == "claude-opus-4-7"
    assert state.cleared
    assert 222 not in handlers._settings_msg_id
    chat_id, message_id, edited_text = bot.edits[0]
    assert (chat_id, message_id) == (222, 555)
    assert "Claude Opus 4.7" in edited_text
    text, markup = message.answers[0]
    assert markup is handlers.MAIN_KB


def test_handle_model_choice_unrecognized_text_reprompts():
    message = FakeMessage(chat_id=333, text="random text")
    state = FakeState()
    bot = FakeBot()
    asyncio.run(handle_model_choice(message, state, bot))
    assert not state.cleared
    assert not bot.edits
    text, markup = message.answers[0]
    assert markup is MODEL_KB
