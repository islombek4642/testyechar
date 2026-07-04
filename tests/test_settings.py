import asyncio

from bot.allowed_users import AllowedUsersStore
from bot.handlers import (
    MODEL_OPTIONS,
    get_selected_model,
    handle_add_user_text,
    handle_model_choice,
    handle_remove_user,
    handle_users_back,
    manage_users_keyboard,
    manage_users_text,
    prompt_add_user,
    settings_keyboard,
    show_manage_users,
    show_settings,
)
from bot.states import Mode


class FakeChat:
    def __init__(self, id):
        self.id = id


class FakeUser:
    def __init__(self, id):
        self.id = id


class FakeSentMessage:
    def __init__(self, message_id):
        self.message_id = message_id
        self.edits = []
        self.deleted = False

    async def edit_text(self, text, **kwargs):
        self.edits.append((text, kwargs.get("reply_markup")))

    async def delete(self):
        self.deleted = True


class FakeMessage:
    def __init__(self, chat_id, user_id=None, text=None):
        self.chat = FakeChat(chat_id)
        self.from_user = FakeUser(user_id if user_id is not None else chat_id)
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
    def __init__(self, model, admin_id=1):
        self.model = model
        self.admin_id = admin_id


class FakeBot:
    def __init__(self):
        self.edits = []  # list of (chat_id, message_id, text)

    async def edit_message_text(self, chat_id, message_id, text, **kwargs):
        self.edits.append((chat_id, message_id, text))


class FakeCallback:
    def __init__(self, data, message, user_id):
        self.data = data
        self.message = message
        self.from_user = FakeUser(user_id)
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


def test_settings_keyboard_marks_selected_and_hides_admin_row_for_non_admin():
    kb = settings_keyboard("claude-opus-4-7", is_admin=False)
    texts = [row[0].text for row in kb.keyboard]
    assert texts == ["Claude Opus 4.8", "✅ Claude Opus 4.7", "Claude Sonnet 5"]


def test_settings_keyboard_adds_manage_users_row_for_admin():
    kb = settings_keyboard("claude-opus-4-8", is_admin=True)
    texts = [row[0].text for row in kb.keyboard]
    assert texts[-1] == "👥 Foydalanuvchilar"
    assert len(texts) == 4


def test_get_selected_model_falls_back_to_default():
    assert get_selected_model(424242, "claude-opus-4-8") == "claude-opus-4-8"


def test_show_settings_switches_state_and_marks_current_model():
    message = FakeMessage(chat_id=111, user_id=999)  # not admin
    state = FakeState()
    settings = FakeSettings(model="claude-opus-4-8", admin_id=1)
    asyncio.run(show_settings(message, state, settings))
    assert state.set_to == Mode.choosing_model
    text, markup = message.answers[0]
    assert "Claude Opus 4.8" in text
    button_texts = [row[0].text for row in markup.keyboard]
    assert button_texts == ["✅ Claude Opus 4.8", "Claude Opus 4.7", "Claude Sonnet 5"]


def test_show_settings_shows_manage_users_button_for_admin():
    message = FakeMessage(chat_id=111, user_id=1)
    state = FakeState()
    settings = FakeSettings(model="claude-opus-4-8", admin_id=1)
    asyncio.run(show_settings(message, state, settings))
    _, markup = message.answers[0]
    button_texts = [row[0].text for row in markup.keyboard]
    assert "👥 Foydalanuvchilar" in button_texts


def test_handle_model_choice_stores_preference_edits_old_message_and_returns_to_menu():
    message = FakeMessage(chat_id=222, user_id=222, text="Claude Opus 4.7")
    state = FakeState()
    bot = FakeBot()
    settings = FakeSettings(model="claude-opus-4-8", admin_id=1)
    from bot import handlers

    handlers._settings_msg_id[222] = 555

    asyncio.run(handle_model_choice(message, state, bot, settings))

    assert get_selected_model(222, "claude-opus-4-8") == "claude-opus-4-7"
    assert state.cleared
    assert 222 not in handlers._settings_msg_id
    chat_id, message_id, edited_text = bot.edits[0]
    assert (chat_id, message_id) == (222, 555)
    assert "Claude Opus 4.7" in edited_text
    text, markup = message.answers[0]
    assert markup is handlers.MAIN_KB


def test_handle_model_choice_accepts_already_checked_label():
    # Re-tapping the currently-selected button sends its "✅ " prefixed text back.
    message = FakeMessage(chat_id=223, user_id=223, text="✅ Claude Sonnet 5")
    state = FakeState()
    bot = FakeBot()
    settings = FakeSettings(model="claude-opus-4-8", admin_id=1)
    asyncio.run(handle_model_choice(message, state, bot, settings))
    assert get_selected_model(223, "claude-opus-4-8") == "claude-sonnet-5"


def test_handle_model_choice_unrecognized_text_reprompts():
    message = FakeMessage(chat_id=333, user_id=333, text="random text")
    state = FakeState()
    bot = FakeBot()
    settings = FakeSettings(model="claude-opus-4-8", admin_id=1)
    asyncio.run(handle_model_choice(message, state, bot, settings))
    assert not state.cleared
    assert not bot.edits
    text, markup = message.answers[0]
    assert [row[0].text for row in markup.keyboard][:3] == [
        "✅ Claude Opus 4.8",
        "Claude Opus 4.7",
        "Claude Sonnet 5",
    ]


def test_show_manage_users_denies_non_admin():
    message = FakeMessage(chat_id=444, user_id=999)
    state = FakeState()
    settings = FakeSettings(model="claude-opus-4-8", admin_id=1)

    class FakeAllowedUsers:
        def list_ids(self):
            raise AssertionError("should not be called for a non-admin")

    asyncio.run(show_manage_users(message, state, settings, FakeAllowedUsers()))
    assert state.cleared
    text, markup = message.answers[0]
    assert "faqat admin" in text.lower()


def test_show_manage_users_lists_ids_for_admin(tmp_path):
    message = FakeMessage(chat_id=444, user_id=1)
    state = FakeState()
    settings = FakeSettings(model="claude-opus-4-8", admin_id=1)
    store = AllowedUsersStore(admin_id=1, path=tmp_path / "allowed.json", seed=[111, 222])

    asyncio.run(show_manage_users(message, state, settings, store))

    assert state.set_to == Mode.managing_users
    text, markup = message.answers[0]
    assert "111" in text and "222" in text
    callback_data = [row[0].callback_data for row in markup.inline_keyboard]
    assert "deluser:111" in callback_data
    assert "deluser:222" in callback_data


def test_manage_users_text_empty_list():
    assert "yo'q" in manage_users_text([]).lower()


def test_manage_users_keyboard_has_add_and_back_rows():
    kb = manage_users_keyboard([111])
    callback_data = [row[0].callback_data for row in kb.inline_keyboard]
    assert callback_data == ["deluser:111", "adduser:prompt", "users:back"]


def test_prompt_add_user_denies_non_admin():
    message = FakeMessage(chat_id=444, user_id=444)
    cb = FakeCallback(data="adduser:prompt", message=message, user_id=999)
    state = FakeState()
    settings = FakeSettings(model="claude-opus-4-8", admin_id=1)
    asyncio.run(prompt_add_user(cb, state, settings))
    assert state.set_to is None
    assert cb.answers[0] == "⛔ Ruxsat yo'q."


def test_prompt_add_user_sets_state_for_admin():
    message = FakeMessage(chat_id=444, user_id=1)
    cb = FakeCallback(data="adduser:prompt", message=message, user_id=1)
    state = FakeState()
    settings = FakeSettings(model="claude-opus-4-8", admin_id=1)
    asyncio.run(prompt_add_user(cb, state, settings))
    assert state.set_to == Mode.adding_user
    assert message.answers  # prompt text sent


def test_handle_add_user_text_valid_id(tmp_path):
    message = FakeMessage(chat_id=444, user_id=1, text="123456")
    state = FakeState()
    store = AllowedUsersStore(admin_id=1, path=tmp_path / "allowed.json")
    asyncio.run(handle_add_user_text(message, state, store))
    assert store.is_allowed(123456)
    assert state.cleared
    text, markup = message.answers[0]
    assert "123456" in text


def test_handle_add_user_text_rejects_non_numeric(tmp_path):
    message = FakeMessage(chat_id=444, user_id=1, text="not a number")
    state = FakeState()
    store = AllowedUsersStore(admin_id=1, path=tmp_path / "allowed.json")
    asyncio.run(handle_add_user_text(message, state, store))
    assert not state.cleared
    assert store.list_ids() == []


def test_handle_remove_user_denies_non_admin(tmp_path):
    message = FakeMessage(chat_id=444, user_id=444)
    cb = FakeCallback(data="deluser:111", message=message, user_id=999)
    settings = FakeSettings(model="claude-opus-4-8", admin_id=1)
    store = AllowedUsersStore(admin_id=1, path=tmp_path / "allowed.json", seed=[111])
    asyncio.run(handle_remove_user(cb, settings, store))
    assert store.is_allowed(111)  # unchanged
    assert cb.answers[0] == "⛔ Ruxsat yo'q."


def test_handle_remove_user_removes_and_edits_list(tmp_path):
    sent = FakeSentMessage(1)
    cb = FakeCallback(data="deluser:111", message=sent, user_id=1)
    settings = FakeSettings(model="claude-opus-4-8", admin_id=1)
    store = AllowedUsersStore(admin_id=1, path=tmp_path / "allowed.json", seed=[111, 222])

    asyncio.run(handle_remove_user(cb, settings, store))

    assert not store.is_allowed(111)
    assert store.is_allowed(222)
    edited_text, _ = sent.edits[0]
    assert "111" not in edited_text
    assert "222" in edited_text


def test_handle_users_back_clears_state_and_restores_main_menu():
    message = FakeMessage(chat_id=444, user_id=1)
    cb = FakeCallback(data="users:back", message=message, user_id=1)
    state = FakeState()
    asyncio.run(handle_users_back(cb, state))
    assert state.cleared
    assert any(markup is not None for _, markup in message.answers)
