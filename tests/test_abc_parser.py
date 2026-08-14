from app.parser.abc_parser import ABCParser
from app.parser.parser import QuestionParser


SAMPLE = """
1. Vitaminning butunlay yo'qolishi natijasida kelib chiqadigan holat nima deb ataladi?
A) Gipovitaminoz
B) Gipervitaminoz
C) Avitaminoz*
D) Poligipovitaminoz

2. Qanday holatda vitaminning qisman yetishmovchiligi kuzatiladi?
A) Avitaminoz
B) Gipovitaminoz*
C) Gipervitaminoz
D) Beri-beri kasalligi

3. "A" vitaminining ortiqcha miqdordan iste'mol qilishidan kelib chiqadigan holat...
A) Skarbut kasalligi
B) Raxit kasalligi
C) Gipervitaminoz A*
D) Pellagra kasalligi

4. Suvda eruvchi vitaminlar guruhiiga kirmaydigan vitamin:
A) Askorbin kislota vitamini
B) Tiamin vitamini
C) Tokoferol vitamini*
D) Niyatsin
"""


def test_abc_parser_supports_trailing_star_correct_marker():
    questions = ABCParser().parse(SAMPLE.splitlines())

    assert len(questions) == 4

    expected_correct_index = [2, 1, 2, 2]
    for q, correct_idx in zip(questions, expected_correct_index):
        assert len(q.options) == 4
        correct_options = [i for i, o in enumerate(q.options) if o.is_correct]
        assert correct_options == [correct_idx]
        # The trailing "*" marker must be stripped from the option text.
        assert not q.options[correct_idx].text.endswith("*")


def test_abc_parser_still_supports_leading_hash_marker():
    lines = [
        "1. Savol matni?",
        "A) Noto'g'ri javob",
        "#B) To'g'ri javob",
        "C) Noto'g'ri javob",
    ]
    questions = ABCParser().parse(lines)

    assert len(questions) == 1
    correct_options = [i for i, o in enumerate(questions[0].options) if o.is_correct]
    assert correct_options == [1]
    assert questions[0].options[1].text == "To'g'ri javob"


def test_abc_parser_supports_cyrillic_option_letters():
    """Some Russian test banks letter their options А) Б) В) Г) (Cyrillic)
    instead of A) B) C) D) (Latin) -- same 4-way structure, different
    alphabet. Format auto-detection must route these to ABCParser too."""
    text = (
        "35. Мальчик очень вежлив …\n"
        "А) Со всем\n"
        "Б) Со всеми\n"
        "В) Всем\n"
        "Г) Всеми\n"
        "36. ……мы поедем на каникулы.\n"
        "А) Через несколько дней\n"
        "Б) Несколько дней\n"
        "В) За несколько дней\n"
        "Г) С несколько дней\n"
    )
    parser = QuestionParser()
    questions = parser.parse(text)

    assert len(questions) == 2
    assert questions[0].question_text == "Мальчик очень вежлив …"
    assert [o.text for o in questions[0].options] == [
        "Со всем", "Со всеми", "Всем", "Всеми",
    ]


def test_abc_parser_correct_answer_line_supports_cyrillic_letter():
    lines = [
        "1. Savol matni?",
        "А) Noto'g'ri javob",
        "Б) To'g'ri javob",
        "В) Noto'g'ri javob",
        "Ответ: Б",
    ]
    questions = ABCParser().parse(lines)

    assert len(questions) == 1
    correct_options = [i for i, o in enumerate(questions[0].options) if o.is_correct]
    assert correct_options == [1]


def test_abc_parser_skips_section_header_between_questions():
    """"ЧАСТЬ N. Вопросы ..." section headers some test banks insert
    between question groups must be dropped, not folded into the
    preceding option as a continuation line."""
    lines = [
        "1. Savol matni?",
        "А) variant1",
        "Б) variant2",
        "ЧАСТЬ 2. Вопросы 2-5: выберите свой вариант ответа.",
        "2. Ikkinchi savol?",
        "А) variant3",
        "Б) variant4",
    ]
    questions = ABCParser().parse(lines)

    assert len(questions) == 2
    assert questions[0].options[-1].text == "variant2"
    assert questions[1].question_text == "Ikkinchi savol?"


def test_abc_parser_skips_typo_section_header_missing_soft_sign():
    """A section header typo'd without the trailing "ь" ("ЧАСТ 4." instead
    of "ЧАСТЬ 4.") must still be recognized and skipped, not glued onto
    the preceding option."""
    lines = [
        "1. Savol matni?",
        "А) variant1",
        "Б) variant2",
        "ЧАСТ 4. Вопросы 97-100 выберите все возможные варианты.",
        "2. Ikkinchi savol?",
        "А) variant3",
        "Б) variant4",
    ]
    questions = ABCParser().parse(lines)

    assert len(questions) == 2
    assert questions[0].options[-1].text == "variant2"


def test_section_header_regex_does_not_match_ordinary_words():
    """Ordinary Russian words sharing the "част-" stem ("частица",
    "частный", "частота") must not be mistaken for a section header --
    only the header form (stem + digit) should match."""
    from app.parser.abc_parser import _SECTION_HEADER_RE

    for word in ["частица", "Частный случай", "частота колебаний"]:
        assert _SECTION_HEADER_RE.match(word) is None
