from app.extractor.pdf_extractor import _GLUED_FRAGMENT, _GLUED_QUESTION


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


def test_glued_question_pattern_ignores_single_mixed_case_word():
    """Intentional capitalization-test options ("мАРИЯ", "ЯнВарь" -- a single
    word with deliberately wrong internal casing, used to test whether a
    reader can spot the right capitalization) must NOT be mistaken for a
    glued second sentence just because they contain a lowercase->uppercase
    transition -- the tail has no space, so it's one word, not two glued
    sentences."""
    for line in ["= мАРИЯ", "= ЯнВарь", "= школаА"]:
        assert _GLUED_QUESTION.search(line) is None
        assert _GLUED_FRAGMENT.search(line) is None


def test_glued_fragment_pattern_matches_orphaned_non_question_tail():
    """Same glue defect, but the second content run never reaches its own
    "?" (a leftover/incomplete question stem in the source PDF with no
    continuation nearby) -- there's nowhere sensible to place it, so it
    should be recognized for dropping rather than left polluting the
    option's text."""
    stripped = "= пише_тКак правильно пишется существительное с окончанием -а"
    assert _GLUED_QUESTION.search(stripped) is None  # no "?" -- not a question split
    m = _GLUED_FRAGMENT.search(stripped)
    assert m is not None
    assert m.group(2) == "Как правильно пишется существительное с окончанием -а"
    assert stripped[: m.start(2)] == "= пише_т"
