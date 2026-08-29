from app.models.question import RawOption, RawQuestion
from app.validator.question_validator import QuestionValidator


def _raw(options_text, line_start=1):
    return RawQuestion(
        question_text="Savol matni?",
        options=[RawOption(text=t) for t in options_text],
        line_start=line_start,
    )


def test_four_options_gets_no_option_count_warning():
    results = QuestionValidator().validate_all([_raw(["a", "b", "c", "d"])])
    assert results[0].is_valid
    assert not any("ta variant aniqlandi" in w for w in results[0].warnings)


def test_non_four_option_count_is_flagged_for_review():
    results = QuestionValidator().validate_all([_raw(["a", "b", "c"])])
    assert results[0].is_valid  # still valid -- just flagged for a human to check
    assert any("4 emas, 3 ta variant aniqlandi" in w for w in results[0].warnings)


def test_duplicate_option_keeps_correct_flag_from_later_occurrence():
    """When the same option text appears twice and only the LATER copy is
    marked correct (e.g. the PDF genuinely repeats an option, and only one
    physical instance happened to be bold-detected as the answer), the
    surviving (first) copy must inherit that correct flag rather than
    silently losing it because the earlier, unmarked copy was kept."""
    raw = RawQuestion(
        question_text="Savol matni?",
        options=[
            RawOption(text="Добраться", is_correct=False),
            RawOption(text="Дойти", is_correct=False),
            RawOption(text="Добраться", is_correct=True),
        ],
        line_start=1,
    )
    results = QuestionValidator().validate_all([raw])

    assert results[0].is_valid
    q = results[0].question
    assert q.o == ["Добраться", "Дойти"]
    assert q.c == 0


def test_stray_empty_option_not_at_end_does_not_misattribute_correct_flag():
    """A RawQuestion with an empty-text option BEFORE the correct one must
    not have its correct-answer flag land on the wrong option. Filtering
    empty option TEXT first and then zip()-ing the filtered text list
    against the unfiltered RawOption list misaligns every option from the
    empty one onward -- the correct flag silently lands on the option
    physically after it (here, "d" would wrongly read as correct, and "c"
    would lose its flag) instead of staying on "c"."""
    raw = RawQuestion(
        question_text="Savol matni?",
        options=[
            RawOption(text="a", is_correct=False),
            RawOption(text="b", is_correct=False),
            RawOption(text="", is_correct=False),  # stray empty option
            RawOption(text="c", is_correct=True),
            RawOption(text="d", is_correct=False),
        ],
        line_start=1,
    )
    results = QuestionValidator().validate_all([raw])

    assert results[0].is_valid
    q = results[0].question
    assert q.o == ["a", "b", "c", "d"]
    assert q.c == 2
    assert q.o[q.c] == "c"
