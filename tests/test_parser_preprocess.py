from app.parser.parser import QuestionParser


def test_no_option_markers_preprocessing_skips_dash_marked_documents():
    """A document whose questions have no "-"/"="/"+" marker of their own
    but whose OPTIONS already use "-" as a wrong-answer marker (and "+" for
    the correct one) must not be mistaken for the "no markers at all"
    format. Previously the trigger only counted "="/"+"/"*" lines, missing
    "-" entirely, so a dash-marked document's already-correct option lines
    got a second "=" prepended on top ("- text" -> "= - text"), corrupting
    every option's text and, worse, silently losing which one was correct
    (the "+"-marked option became "= + text", a WRONG option whose text
    still carried a stray "+")."""
    lines = [f"? Savol {i}?\n- a\n- b\n+ c\n- d" for i in range(1, 4)]
    text = "\n".join(lines)

    parser = QuestionParser()
    converted = parser._preprocess_no_option_markers(text)

    assert converted is None  # heuristic must not activate


def test_no_option_markers_preprocessing_still_activates_when_truly_markerless():
    """Sanity check the heuristic still fires for its actual target format:
    "?" questions whose options carry no marker of any kind."""
    lines = [f"? Savol {i}?\na text\nb text\nc text\nd text" for i in range(1, 4)]
    text = "\n".join(lines)

    parser = QuestionParser()
    converted = parser._preprocess_no_option_markers(text)

    assert converted is not None
    assert "= a text" in converted
