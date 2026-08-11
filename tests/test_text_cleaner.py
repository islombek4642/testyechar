from app.cleaner.text_cleaner import TextCleaner


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
