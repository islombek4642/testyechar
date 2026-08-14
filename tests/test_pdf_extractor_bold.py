import fitz

from app.extractor.pdf_extractor import PDFExtractor


def _make_pdf(tmp_path):
    """Build a tiny synthetic PDF where option "B)" is bold and the rest
    (including the question line, which is bold too, same as real test
    banks) are not -- mirrors the "correct option is the only bold run
    among its siblings" convention some Russian test banks use instead of
    a highlight box."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), "1. Question text", fontname="hebo", fontsize=11)
    page.insert_text((50, 70), "A) wrong", fontname="helv", fontsize=11)
    page.insert_text((50, 90), "B) correct", fontname="hebo", fontsize=11)
    page.insert_text((50, 110), "C) wrong", fontname="helv", fontsize=11)
    path = tmp_path / "bold_option.pdf"
    doc.save(str(path))
    doc.close()
    return path


def test_bold_option_line_gets_marked_correct(tmp_path):
    path = _make_pdf(tmp_path)
    result = PDFExtractor().extract(path)
    text = result.full_text

    assert "#B) correct" in text
    assert "#A" not in text
    assert "#C" not in text
    # The bold question line itself must not be treated as an option.
    assert "#1." not in text
