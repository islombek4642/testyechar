from app.models.question import ParsedQuestion

from bot.classic_txt import to_classic_txt


def test_classic_txt_marks_correct_option():
    qs = [
        ParsedQuestion(q="Savol 1?", o=["A", "B", "C"], c=1),
        ParsedQuestion(q="Savol 2?", o=["X", "Y"], c=0),
    ]
    txt = to_classic_txt(qs)
    assert txt == (
        "? Savol 1?\n"
        "= A\n"
        "+ B\n"
        "= C\n"
        "\n"
        "? Savol 2?\n"
        "+ X\n"
        "= Y\n"
    )


def test_classic_txt_empty_list():
    assert to_classic_txt([]) == ""
