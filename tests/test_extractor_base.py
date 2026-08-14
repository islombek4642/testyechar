from app.extractor.pdf_extractor import PDFExtractor


def test_fix_all_correct_stops_scan_at_section_header():
    """A "ЧАСТЬ N. ..." section header between one question's options and
    the next question group must stop fix_all_correct's option-collecting
    scan. Without this, the scan silently runs past the header (it's
    neither a recognized question start nor an option marker) and sweeps
    later questions' "#"-marked correct options into the CURRENT question's
    tally -- once 2+ end up collected there, the "all options correct ->
    decorative highlight, strip the markers" heuristic wrongly fires and
    erases this question's own, entirely legitimate, single correct mark."""
    lines = [
        "13. Savol matni?",
        "#А) to'g'ri javob",
        "Б) noto'g'ri",
        "В) noto'g'ri",
        "Г) noto'g'ri",
        "ЧАСТЬ 2. Вопросы 18-20: выберите свой вариант ответа.",
        "18. Ikkinchi savol?",
        "А) noto'g'ri",
        "#Б) to'g'ri javob 2",
        "В) noto'g'ri",
    ]
    fixed = PDFExtractor.fix_all_correct(lines)

    assert fixed[1] == "#А) to'g'ri javob"
    assert fixed[8] == "#Б) to'g'ri javob 2"
