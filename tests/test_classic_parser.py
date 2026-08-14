from app.parser.classic_parser import ClassicParser
from app.parser.parser import QuestionParser


def test_split_merged_option_lines_recovers_embedded_correct_marker():
    """A PDF row that glued a wrong option and the correct one together
    ("...topshirildi. + Sinfimizda...") must still yield 4 separate options
    with the "+" one recognized as correct."""
    text = (
        "? Qaysi gapda otlashgan sifat(lar) qo'llanmagan.\n"
        "= Yaxshidan bog' qoladi, yomondan - dog'.\n"
        "= Ilg'orlarga mukofot topshirildi. + Sinfimizda a'lochi o'quvchilar ko'p.\n"
        "= Yoshlar olovga yaqinroq, keksalar esa uzoqroq o'tirishdi.\n"
    )
    questions = QuestionParser().parse(text)

    assert len(questions) == 1
    q = questions[0]
    assert len(q.options) == 4
    correct = [i for i, o in enumerate(q.options) if o.is_correct]
    assert correct == [2]
    assert q.options[2].text == "Sinfimizda a'lochi o'quvchilar ko'p."


def test_split_merged_option_lines_ignores_cyrillic_name_initials():
    """"Б. Васильев" (a Russian author's initial + surname) must NOT be
    mistaken for an embedded Cyrillic ABC option marker ("Б) ...") and
    split off from the question it belongs to -- this pattern is common,
    ordinary prose in Russian literature/history question text."""
    text = (
        "? Б. Васильев написал..\n"
        "= Судьба человека\n"
        "= А зори здесь тихие\n"
        "= Тихий Дон\n"
    )
    questions = QuestionParser().parse(text)

    assert len(questions) == 1
    assert questions[0].question_text == "Б. Васильев написал.."
    assert len(questions[0].options) == 3


def test_split_merged_option_lines_ignores_notation_equals_signs():
    """"=" used as plain notation inside a question ("asos = so'z yasovchi
    = ...") must NOT be chopped into fake options -- only "=" that follows
    sentence-ending punctuation is a genuine option boundary."""
    text = (
        "? Morfem tarkibi asos = sz yasovchi = lugaviy shakl yasovchi = "
        "sinataktik shakl yasovchi qolipidagi so'zni toping.\n"
        "+ tokzorlarda\n"
        "= ipakchilikdan\n"
        "= sizlamoq\n"
        "= turmushimizni\n"
    )
    questions = QuestionParser().parse(text)

    assert len(questions) == 1
    q = questions[0]
    assert q.question_text == (
        "Morfem tarkibi asos = sz yasovchi = lugaviy shakl yasovchi = "
        "sinataktik shakl yasovchi qolipidagi so'zni toping."
    )
    assert len(q.options) == 4
    correct = [i for i, o in enumerate(q.options) if o.is_correct]
    assert correct == [0]


def test_classic_parser_merges_numbered_sublist_option_continuations():
    """An option spelled out as a numbered sub-list ("1.Range A") whose
    "2."/"3." continuation lines carry no marker of their own must stay
    part of that SAME option, not get misread as new numbered questions."""
    lines = [
        "? Zaif ko'ruvchilar ko'rish o'tkirligiga ko'ra qanday turga bo'linadi",
        "=1.Ko'ruv o'tkirligi 0,05dan 0,1 gacha",
        "2.Ko'ruv o'tkirligi 0,1dan 0,2 gacha",
        "3.Ko'ruv o'tkirligi 0,2 dan yuqori 0,4 gacha.",
        "= 1.Ko'ruv o'tkirligi 0,01dan 0,4 gacha",
        "2.Ko'ruv o'tkirligi 0,4dan 0,5 gacha",
        "3.Ko'ruv o'tkirligi 0,5 dan yuqori 0,6 gacha.",
        "= 1.Ko'ruv o'tkirligi 0,05dan 0,01 gacha",
        "2.Ko'ruv o'tkirligi 0,01dan 0,1 gacha",
        "3.Ko'ruv o'tkirligi 0,1 dan yuqori 0,2 gacha.",
        "= 1.Ko'ruv o'tkirligi 0,1dan 0,2 gacha",
        "2.Ko'ruv o'tkirligi 0,2dan 0,3 gacha",
        "3.Ko'ruv o'tkirligi 0,3 dan yuqori 0,4gacha.",
        "? Ko'rishida nuqsoni bor bolalarga ta'lim-tarbiya berish jarayonida "
        "qaysi jarayonlariga alohida ahamiyat beriladi",
        "= Eshitish va sezish",
        "= Ko'ruv idrokini rivojlantirishga",
        "= Diqqatni jamlashga",
        "= Mo'ljal olishga o'rgatishga",
    ]
    questions = ClassicParser().parse(lines)

    assert len(questions) == 2

    q1 = questions[0]
    assert len(q1.options) == 4
    for opt in q1.options:
        assert opt.text.count("Ko'ruv o'tkirligi") == 3

    q2 = questions[1]
    assert len(q2.options) == 4
    assert q2.options[0].text == "Eshitish va sezish"
