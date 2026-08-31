from app.cleaner.text_cleaner import TextCleaner

# mark_unmarked_correct_options only activates on a whole-document signal
# (>= 3 questions, "="/"-" markers on every option). Padding with two filler
# questions in this same shape lets each test isolate one specific block's
# behavior while still tripping the trigger.
_PAD = (
    "? Filler savol 1?\n"
    "= a\n"
    "b\n"
    "= c\n"
    "= d\n"
    "? Filler savol 2?\n"
    "= a\n"
    "b\n"
    "= c\n"
    "= d\n"
)


def test_normalize_dashes_collapses_dash_variants_normally():
    text = "= long—dash\n= short–dash\n"
    result = TextCleaner.normalize_dashes(text)
    assert result == "= long-dash\n= short-dash\n"


def test_normalize_dashes_preserves_distinct_dash_glyphs_within_same_option_block():
    """Two sibling options that differ only by dash glyph (hyphen vs.
    em-dash) must stay distinguishable -- collapsing both to a plain
    hyphen would make them read as duplicates and the validator would
    silently drop one, losing a real answer choice (e.g. a punctuation
    quiz testing hyphen vs. em-dash spelling)."""
    text = (
        "? Как пишется слово?\n"
        "= северо-американский\n"
        "= североамериканский\n"
        "= северо американский\n"
        "= северо—американский\n"
    )
    result = TextCleaner.normalize_dashes(text)
    lines = result.splitlines()
    assert lines[1] == "= северо-американский"
    assert lines[4] == "= северо—американский"  # kept distinct, not collapsed to "-"


def test_normalize_dashes_still_collapses_when_no_collision():
    """The em-dash normalizes normally when it doesn't collide with a sibling option."""
    text = "? Q\n= aaa—bbb\n= ccc\n"
    result = TextCleaner.normalize_dashes(text)
    assert result.splitlines()[1] == "= aaa-bbb"


def test_mark_unmarked_correct_options_basic_case():
    """Every WRONG option is "="-marked but the correct one carries no
    marker at all -- a real test-bank format. The bare line, wherever it
    falls among the "=" lines, must get a "+" so ClassicParser doesn't
    fold it into a sibling option's text as a wrapped-word continuation."""
    text = _PAD + (
        "? Savol matni?\n"
        "= 2 ta\n"
        "3 ta\n"
        "= 4 ta\n"
        "= 5 ta\n"
    )
    result = TextCleaner.mark_unmarked_correct_options(text)
    assert "+ 3 ta" in result.splitlines()


def test_mark_unmarked_correct_options_skips_wrapped_question_continuation():
    """A question stem that wraps onto a second PDF line (ending in "?")
    before any "=" option appears must stay unmarked -- it's a
    continuation of the question, not the correct answer."""
    text = _PAD + (
        "? Nima uchun bunday\n"
        "bo'ladi?\n"
        "= sababi noaniq\n"
        "haqiqiy sabab shu\n"
        "= boshqa sabab\n"
        "= yana boshqa sabab\n"
    )
    result = TextCleaner.mark_unmarked_correct_options(text)
    lines = result.splitlines()
    assert "bo'ladi?" in lines  # continuation left untouched
    assert "+ haqiqiy sabab shu" in lines


def test_mark_unmarked_correct_options_correct_answer_ending_in_period():
    """A correct answer is a genuine complete sentence ending in "." (not
    a wrapped continuation of the question) when it is the ONLY unmarked
    line directly adjacent to the first "=" -- must still be marked
    correct, not mistaken for stem-completing punctuation."""
    text = _PAD + (
        "? Nima talab qilinadi\n"
        "hamma narsani rivojlantirish kerak.\n"
        "= variant ikki\n"
        "= variant uch\n"
        "= variant tort\n"
    )
    result = TextCleaner.mark_unmarked_correct_options(text)
    assert "+ hamma narsani rivojlantirish kerak." in result.splitlines()


def test_mark_unmarked_correct_options_multiline_continuation_then_answer():
    """Two unmarked lines before the first "=": an imperative continuation
    ending in "." (not the answer) followed by the real bare correct
    answer. Only the second one gets marked."""
    text = _PAD + (
        "? Savol boshlanishi\n"
        "to'g'ri javobni aniqlang.\n"
        "6-12 oy\n"
        "= 3-6 oy\n"
        "= 2-5 oy\n"
        "= 6-9 oy\n"
    )
    result = TextCleaner.mark_unmarked_correct_options(text)
    lines = result.splitlines()
    assert "to'g'ri javobni aniqlang." in lines
    assert "+ 6-12 oy" in lines


def test_mark_unmarked_correct_options_does_not_activate_when_already_marked():
    """If ANY "+"/"*"/"#" correct-marker already exists in the document,
    this format doesn't apply -- leave the text untouched."""
    text = (
        "? Savol?\n"
        "= a\n"
        "+ b\n"
        "= c\n"
        "= d\n"
        "? Savol 2?\n"
        "= a\n"
        "b\n"
        "= c\n"
        "= d\n"
    )
    result = TextCleaner.mark_unmarked_correct_options(text)
    assert result == text
