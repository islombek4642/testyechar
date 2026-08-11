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
