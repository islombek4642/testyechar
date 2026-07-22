from app.parser.abc_parser import ABCParser


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
