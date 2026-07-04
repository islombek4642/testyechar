import asyncio

from aiogram.types import InlineKeyboardMarkup

from bot.handlers import (
    MODEL_OPTIONS,
    get_selected_model,
    handle_model_choice,
    model_settings_keyboard,
    show_settings,
)


class FakeChat:
    def __init__(self, id):
        self.id = id


class FakeMessage:
    def __init__(self, chat_id):
        self.chat = FakeChat(chat_id)
        self.answers = []
        self.edits = []

    async def answer(self, text, **kwargs):
        self.answers.append((text, kwargs.get("reply_markup")))

    async def edit_text(self, text, **kwargs):
        self.edits.append((text, kwargs.get("reply_markup")))


class FakeSettings:
    def __init__(self, model):
        self.model = model


class FakeCallback:
    def __init__(self, data, message):
        self.data = data
        self.message = message
        self.answers = []

    async def answer(self, text=None, **kwargs):
        self.answers.append(text)


def test_model_options_has_three_models_in_order():
    assert list(MODEL_OPTIONS.keys()) == [
        "claude-opus-4-8",
        "claude-opus-4-7",
        "claude-sonnet-5",
    ]
    assert MODEL_OPTIONS["claude-opus-4-8"] == "Claude Opus 4.8"
    assert MODEL_OPTIONS["claude-opus-4-7"] == "Claude Opus 4.7"
    assert MODEL_OPTIONS["claude-sonnet-5"] == "Claude Sonnet 5"


def test_get_selected_model_falls_back_to_default():
    assert get_selected_model(424242, "claude-opus-4-8") == "claude-opus-4-8"


def test_model_settings_keyboard_marks_selected():
    kb = model_settings_keyboard("claude-opus-4-7")
    texts = [row[0].text for row in kb.inline_keyboard]
    assert texts == ["Claude Opus 4.8", "✅ Claude Opus 4.7", "Claude Sonnet 5"]
    callback_data = [row[0].callback_data for row in kb.inline_keyboard]
    assert callback_data == [
        "model:claude-opus-4-8",
        "model:claude-opus-4-7",
        "model:claude-sonnet-5",
    ]


def test_show_settings_reports_default_model():
    message = FakeMessage(chat_id=111)
    settings = FakeSettings(model="claude-opus-4-8")
    asyncio.run(show_settings(message, settings))
    text, markup = message.answers[0]
    assert "Claude Opus 4.8" in text
    assert isinstance(markup, InlineKeyboardMarkup)
    assert len(markup.inline_keyboard) == 3


def test_handle_model_choice_stores_preference_and_edits_message():
    message = FakeMessage(chat_id=222)
    cb = FakeCallback(data="model:claude-sonnet-5", message=message)
    asyncio.run(handle_model_choice(cb))
    assert get_selected_model(222, "claude-opus-4-8") == "claude-sonnet-5"
    text, _ = message.edits[0]
    assert "Claude Sonnet 5" in text
    assert cb.answers[0] == "✅ Claude Sonnet 5 tanlandi"


def test_handle_model_choice_rejects_unknown_model():
    message = FakeMessage(chat_id=333)
    cb = FakeCallback(data="model:not-a-real-model", message=message)
    asyncio.run(handle_model_choice(cb))
    assert not message.edits
    assert cb.answers[0] == "Noma'lum model."
