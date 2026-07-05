import asyncio
from types import SimpleNamespace

from app.models.question import ParsedQuestion

from bot import handlers
from bot.handlers import (
    MAIN_KB_ADMIN,
    build_ai_raw_questions,
    file_ext,
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


def test_parser_result_keyboard_is_none_when_fully_resolved():
    assert parser_result_keyboard(has_unresolved=False) is None


def test_parser_result_keyboard_shows_ai_button_when_unresolved_exist():
    kb = parser_result_keyboard(has_unresolved=True)
    callback_data = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert callback_data == ["resolve:ai"]


def test_build_ai_raw_questions_marks_already_answered_option_correct():
    questions = [ParsedQuestion(q="2+2?", o=["3", "4", "5"], c=1)]
    raw_ai_qs = build_ai_raw_questions(questions)
    opts = raw_ai_qs[0].question.options
    assert [o.is_correct for o in opts] == [False, True, False]
    assert raw_ai_qs[0].image is None


def test_build_ai_raw_questions_leaves_unmarked_question_all_false():
    questions = [ParsedQuestion(q="Unmarked?", o=["A", "B"], c=-1)]
    raw_ai_qs = build_ai_raw_questions(questions)
    opts = raw_ai_qs[0].question.options
    assert [o.is_correct for o in opts] == [False, False]


def test_build_ai_raw_questions_reads_image_bytes_from_disk(tmp_path, monkeypatch):
    monkeypatch.setattr(handlers, "core_settings", SimpleNamespace(output_dir=tmp_path))
    (tmp_path / "images").mkdir()
    image_path = tmp_path / "images" / "q1.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nfake-bytes")

    questions = [ParsedQuestion(q="With image?", o=["A", "B"], c=-1, img=["images/q1.png"])]
    raw_ai_qs = build_ai_raw_questions(questions)

    assert raw_ai_qs[0].image == b"\x89PNG\r\n\x1a\nfake-bytes"


def test_build_ai_raw_questions_missing_image_file_stays_none(tmp_path, monkeypatch):
    monkeypatch.setattr(handlers, "core_settings", SimpleNamespace(output_dir=tmp_path))
    questions = [ParsedQuestion(q="Ghost image?", o=["A", "B"], c=-1, img=["images/missing.png"])]
    raw_ai_qs = build_ai_raw_questions(questions)
    assert raw_ai_qs[0].image is None


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
