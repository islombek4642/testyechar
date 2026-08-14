import fitz

from app.extractor.pdf_extractor import PDFExtractor


def _make_pdf(tmp_path):
    """A tall decorative shading rect spans 3 lines of plain prose (mimics
    a document's instruction/section background panel); a short, tightly
    fitted highlight rect marks one genuine "=" option as correct."""
    doc = fitz.open()
    page = doc.new_page()

    shape = page.new_shape()
    shape.draw_rect(fitz.Rect(40, 40, 400, 100))
    shape.finish(fill=(0.95, 0.95, 0.95), color=None)
    shape.commit()
    page.insert_text((50, 55), "Decorative heading line one", fontname="helv", fontsize=11)
    page.insert_text((50, 75), "Decorative heading line two", fontname="helv", fontsize=11)
    page.insert_text((50, 95), "Decorative heading line three", fontname="helv", fontsize=11)

    shape2 = page.new_shape()
    shape2.draw_rect(fitz.Rect(40, 118, 200, 132))
    shape2.finish(fill=(1, 1, 0), color=None)
    shape2.commit()
    page.insert_text((45, 129), "= correct option", fontname="helv", fontsize=10)

    path = tmp_path / "tall_vs_short_highlight.pdf"
    doc.save(str(path))
    doc.close()
    return path


def test_tall_decorative_bar_does_not_mark_prose_as_correct(tmp_path):
    path = _make_pdf(tmp_path)
    result = PDFExtractor().extract(path)
    text = result.full_text

    assert "#Decorative" not in text
    assert "Decorative heading line one" in text


def test_short_highlight_still_marks_genuine_option(tmp_path):
    path = _make_pdf(tmp_path)
    result = PDFExtractor().extract(path)
    text = result.full_text

    assert "+ correct option" in text
