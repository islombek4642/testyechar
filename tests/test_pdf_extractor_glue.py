from app.extractor.pdf_extractor import _GLUED_QUESTION


def test_glued_question_pattern_matches_missing_separator_case():
    """PDF content-stream artifact: one answer's text and the next question's
    stem land on the same PyMuPDF "line" with no space between them, e.g.
    "= длинийВ каком слове пишется двойная Р?" -- the split point is the
    lowercase->uppercase boundary right before the embedded new question."""
    stripped = "= длинийВ каком слове пишется двойная Р?"
    m = _GLUED_QUESTION.search(stripped)
    assert m is not None
    assert m.group(2) == "В каком слове пишется двойная Р?"
    assert stripped[: m.start(2)] == "= длиний"


def test_glued_question_pattern_ignores_normal_option_text():
    for line in [
        "= северо-американский",
        "= He failed the exam because he studied.",
        "+ Правильный ответ",
    ]:
        assert _GLUED_QUESTION.search(line) is None
