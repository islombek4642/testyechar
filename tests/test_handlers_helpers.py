import asyncio

from bot.handlers import (
    MAIN_KB_ADMIN,
    file_ext,
    export_keyboard,
    parser_result_keyboard,
    send_status_and_restore_menu,
    PARSER_EXTS,
)


def test_file_ext():
    assert file_ext("Test.PDF") == "pdf"
    assert file_ext("archive.tar.gz") == "gz"
    assert file_ext("noext") == ""
    assert file_ext(None) == ""


def test_ext_sets():
    assert PARSER_EXTS == {"pdf", "docx", "doc", "xlsx", "txt"}


def test_parser_result_keyboard_hides_ai_button_when_fully_resolved():
    kb = parser_result_keyboard(has_unresolved=False)
    callback_data = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert callback_data == ["exp:parser:docx"]


def test_parser_result_keyboard_shows_ai_button_when_unresolved_exist():
    kb = parser_result_keyboard(has_unresolved=True)
    callback_data = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert callback_data == ["exp:parser:docx", "resolve:ai"]


def test_export_keyboard_callback_data():
    kb = export_keyboard("parser")
    buttons = kb.inline_keyboard[0]
    assert [b.callback_data for b in buttons] == ["exp:parser:txt", "exp:parser:docx"]


class _FakeSentMessage:
    def __init__(self, text, reply_markup=None):
        self.text = text
        self.reply_markup = reply_markup
        self.deleted = False

    async def delete(self):
        self.deleted = True


class _FakeMessage:
    def __init__(self):
        self.answers = []

    async def answer(self, text, **kwargs):
        sent = _FakeSentMessage(text, kwargs.get("reply_markup"))
        self.answers.append(sent)
        return sent


def test_send_status_and_restore_menu_keeps_carrier_and_returns_status():
    message = _FakeMessage()

    status = asyncio.run(
        send_status_and_restore_menu(message, "⏳ Tahlil qilinmoqda…", MAIN_KB_ADMIN)
    )

    assert len(message.answers) == 2
    carrier, returned_status = message.answers
    assert carrier.reply_markup is MAIN_KB_ADMIN
    assert carrier.deleted is False  # endi o'chirilmaydi — ishonchlilik uchun
    assert returned_status is status
    assert status.text == "⏳ Tahlil qilinmoqda…"
    assert status.reply_markup is None
