"""
PyMuPDF-based PDF text extractor with highlight detection.

Extracts plain text from each page efficiently, preserving unicode
(including Uzbek Latin, Cyrillic, Arabic). Automatically detects
highlighted options and converts them to correct answers (+ / #).
"""

from __future__ import annotations

from pathlib import Path
import re

import fitz  # PyMuPDF

from app.utils.logger import get_logger
from .base import BaseExtractor, ExtractionResult
from .matrix_reconstructor import fix_matrices_in_text
from .vector_arrow_fixer import fix_vector_arrows

log = get_logger(__name__)


class PDFExtractor(BaseExtractor):
    """
    Concrete PDF extractor using PyMuPDF (fitz).

    Features:
    - Page-by-page extraction (memory-efficient)
    - Unicode-safe (handles Uzbek Latin, Cyrillic, CJK)
    - Highlight detection (yellow/bright background option highlighting)
    - Never crashes — all errors are caught and logged
    """

    @property
    def name(self) -> str:
        return "PyMuPDF"

    def extract(self, path: Path) -> ExtractionResult:
        """
        Open *path* and extract text from every page, detecting highlighted options.

        Returns:
            ExtractionResult with `pages` list populated, even on error.
        """
        log.info(f"[bold cyan]Opening PDF[/]: {path.name}")

        pages: list[str] = []

        try:
            doc = fitz.open(str(path))
        except fitz.FileDataError as exc:
            log.error(f"Corrupted PDF — cannot open: {exc}")
            return ExtractionResult(
                pages=[],
                page_count=0,
                source_path=path,
                extractor_name=self.name,
            )
        except Exception as exc:
            log.error(f"Unexpected error opening PDF: {exc}")
            return ExtractionResult(
                pages=[],
                page_count=0,
                source_path=path,
                extractor_name=self.name,
            )

        page_count = len(doc)
        log.info(f"PDF has [bold]{page_count}[/] page(s)")

        from app.config import settings
        img_dir = settings.images_dir
        img_dir.mkdir(parents=True, exist_ok=True)
        img_prefix = path.stem

        # --- Pass 1: extract all pages (with highlight detection per page) ---
        for page_num, page in enumerate(doc, start=1):
            try:
                text = self._extract_page_with_highlights(
                    page, doc, page_num, img_dir, img_prefix
                )
                pages.append(text)
                log.debug(
                    f"  Page {page_num}/{page_count}: "
                    f"{len(text)} chars extracted"
                )
            except Exception as exc:
                log.warning(f"  Page {page_num}: extraction failed, falling back — {exc}")
                try:
                    pages.append(page.get_text("text"))
                except Exception:
                    pages.append("")

        doc.close()

        # --- Pass 2: apply shared highlight post-processing ---
        # If the PDF already has explicit '+' markers, highlight conversion
        # was unnecessary — revert any over-conversion caused by decorative
        # highlights (all-options-highlighted case).
        all_lines = "\n".join(pages).splitlines()
        if not self.has_explicit_correct(all_lines):
            # No explicit '+' → highlights were the only source;
            # fix the all-correct case (decorative highlight)
            fixed = self.fix_all_correct(all_lines)
            combined = "\n".join(fixed)
            # Re-split back into per-page chunks by character offset
            pages = self._redistribute_pages(pages, combined)
        else:
            log.debug("PDF has explicit '+' markers — skipping highlight post-processing.")

        result = ExtractionResult(
            pages=pages,
            page_count=page_count,
            source_path=path,
            extractor_name=self.name,
        )

        log.info(
            f"Extraction complete — "
            f"{result.character_count:,} characters across {page_count} pages"
        )

        if result.is_empty:
            log.warning(
                "PDF appears to contain no extractable text. "
                "Consider enabling OCR for scanned documents."
            )

        return result

    @staticmethod
    def _redistribute_pages(original_pages: list[str], fixed_text: str) -> list[str]:
        """
        Re-split the post-processed combined text back into per-page chunks,
        preserving the original page boundary line counts.
        """
        fixed_lines = fixed_text.splitlines()
        result: list[str] = []
        offset = 0
        for page_text in original_pages:
            n = len(page_text.splitlines())
            chunk = fixed_lines[offset: offset + n]
            result.append("\n".join(chunk))
            offset += n
        # Any remaining lines go into the last page
        if offset < len(fixed_lines) and result:
            result[-1] += "\n" + "\n".join(fixed_lines[offset:])
        return result

    # ── Super/subscript LaTeX detection ────────────────────────────────
    #
    # dy = base_y - span_y  (positive → span is higher on page)
    #
    #  dy > 5.5              → fraction numerator (√2, √3…) — keep plain,
    #                          text cleaner will add the slash later
    #  1.5 < dy ≤ 5.5        → true superscript → ^{...}  (lone "0" → °)
    #  -6.0 ≤ dy < -1.5      → true subscript   → _{...}  (log base etc.)
    #  dy < -6.0             → fraction denominator — keep plain,
    #                          text cleaner will add the slash later
    #
    _FRAC_NUM_THRESHOLD = 5.5   # above this: fraction numerator
    _SUP_THRESHOLD      = 1.5   # above this (and ≤ _FRAC_NUM): superscript
    _SUB_THRESHOLD      = -1.5  # below this (and ≥ _FRAC_DEN): subscript
    _FRAC_DEN_THRESHOLD = -6.0  # below this: fraction denominator
    _SMALL_RATIO        = 0.85  # span is "small" when size < base_size * this

    def _spans_to_text(self, spans: list) -> str:
        """
        Reconstruct one PDF line from its spans, applying LaTeX notation
        for detected superscripts and subscripts.
        """
        if not spans:
            return ""

        non_empty = [s for s in spans if s["text"].strip()]
        if not non_empty:
            return "".join(s["text"] for s in spans)

        base_size = max(s["size"] for s in non_empty)
        base_ys = [s["origin"][1] for s in non_empty
                   if s["size"] >= base_size * self._SMALL_RATIO]
        base_y = sum(base_ys) / len(base_ys) if base_ys else 0.0

        result = ""
        for span in spans:
            text = span["text"]
            size = span["size"]

            if not text.strip() or size >= base_size * self._SMALL_RATIO:
                result += text
                continue

            dy = base_y - span["origin"][1]
            stripped = text.strip()

            if dy > self._FRAC_NUM_THRESHOLD:
                result += text                          # fraction numerator — keep plain
            elif dy > self._SUP_THRESHOLD:
                result += "°" if stripped == "0" else f"^{{{stripped}}}"
            elif self._FRAC_DEN_THRESHOLD <= dy < self._SUB_THRESHOLD:
                result += f"_{{{stripped}}}"            # true subscript (log base etc.)
            else:
                result += text                          # fraction denominator or borderline

        return result

    # ── Wrap Continuation Detection ────────────────────────────────────

    @staticmethod
    def _is_wrapped_continuation(prev_text: str, curr_text: str) -> bool:
        """
        Determine whether curr_text is a wrapped continuation of prev_text.

        Returns False (not a continuation) when:
        - The current line starts with an uppercase letter (after optional
          leading punctuation such as a quote mark), indicating a new
          sentence or option rather than a mid-sentence fragment; OR
        - The current line starts with words that already appear at the end
          of the previous line — this indicates two SEPARATE options that
          happen to share vocabulary.

        Words of 2 characters or fewer (conjunctions/prepositions like "va",
        "bu") are ignored to avoid false negatives on dangling conjunctions.
        """
        def _clean_words(text: str) -> list[str]:
            return [
                w.strip(".,;:?!").lower()
                for w in text.strip().split()
                if len(w.strip(".,;:?!")) > 2
            ]

        prev_words = _clean_words(prev_text)
        curr_words = _clean_words(curr_text)

        if not prev_words or not curr_words:
            return True

        # A genuine wrapped continuation is a sentence fragment whose first
        # word is typically lowercase. If the first letter of the candidate
        # line (after any leading punctuation such as quotes or spaces) is
        # uppercase, the line most likely starts a new sentence or option —
        # not a continuation of the previous wrapped line.
        for ch in curr_text.strip():
            if ch.isalpha():
                if ch.isupper():
                    return False
                break

        prev_tail = set(prev_words[-3:])   # last 3 key words of previous line
        curr_head = curr_words[:3]          # first 3 key words of current line

        # Any overlap between the end of prev and the start of curr means
        # these are likely different sentences/options, not a wrap.
        return not any(w in prev_tail for w in curr_head)

    # ── Highlight Detection Helpers ─────────────────────────────────────

    def _is_highlighted(
        self,
        bbox: tuple[float, float, float, float],
        highlight_rects: list[tuple[float, float, float, float]],
    ) -> bool:
        """Check if a text bounding box intersects significantly with highlight rects."""
        lx0, ly0, lx1, ly1 = bbox
        line_h = ly1 - ly0
        if line_h <= 0:
            return False

        for hx0, hy0, hx1, hy1 in highlight_rects:
            # Check horizontal overlap
            if lx1 < hx0 or lx0 > hx1:
                continue
            # Check vertical overlap (at least 40% vertical overlap)
            overlap_y = max(0.0, min(ly1, hy1) - max(ly0, hy0))
            if (overlap_y / line_h) > 0.4:
                return True
        return False

    def _extract_page_with_highlights(
        self,
        page: fitz.Page,
        doc: fitz.Document | None = None,
        page_num: int = 0,
        img_dir: Path | None = None,
        img_prefix: str = "",
    ) -> str:
        """Extract text from page and convert colored options to correct markers."""
        highlight_rects: list[tuple[float, float, float, float]] = []

        # 1. Collect highlight annotations (type 8 in PDF specs)
        try:
            annots = page.annots()
            if annots:
                for annot in annots:
                    if annot.type and annot.type[0] == 8:
                        rect = annot.rect
                        if rect:
                            highlight_rects.append((rect.x0, rect.y0, rect.x1, rect.y1))
        except Exception as e:
            log.debug(f"Error reading page annotations: {e}")

        # 2. Collect drawing highlights (yellow or bright vector fills)
        try:
            for path in page.get_drawings():
                fill = path.get("fill")
                rect = path.get("rect")
                if fill and rect:
                    r, g, b = fill[:3]
                    # Highlight colors are bright (sum of channels is high)
                    if (r + g + b) > 1.4:
                        rx0, ry0, rx1, ry1 = rect
                        w = rx1 - rx0
                        h = ry1 - ry0
                        # Highlight blocks are wide bars
                        if w > 0 and h > 0 and (w / h) > 1.2:
                            highlight_rects.append((rx0, ry0, rx1, ry1))
        except Exception as e:
            log.debug(f"Error reading page drawings: {e}")

        # 3. Read structured text blocks — always via dict for LaTeX super/sub detection
        # Collect (line_str, x1, y0) pairs first, then join wrapped continuations
        raw_lines: list[tuple[str, float, float]] = []  # (text, x1, y0)
        _img_counter: list[int] = [0]  # mutable per-page image counter

        try:
            text_dict = page.get_text("dict")
            blocks = text_dict.get("blocks", [])
            # Image tokens collected separately so we can insert them at the
            # correct y-position without reordering text blocks.  Sorting ALL
            # blocks by y would disrupt PDFs where math fractions span multiple
            # blocks whose y-coordinates don't match their logical reading order.
            pending_img_tokens: list[tuple[str, float]] = []  # (token, y0)

            for block in blocks:
                btype = block.get("type")

                # ── Image block: extract and store token with its y-position ─
                if btype == 1 and doc is not None and img_dir is not None:
                    bbox = block.get("bbox")
                    if bbox:
                        bx0, by0, bx1, by1 = bbox
                        w, h = bx1 - bx0, by1 - by0
                        # Skip tiny decorative elements (< 30×30 pt)
                        if w >= 30 and h >= 30:
                            try:
                                rect = fitz.Rect(bbox)
                                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=rect)
                                img_filename = f"{img_prefix}_p{page_num}_i{_img_counter[0]}.png"
                                pix.save(str(img_dir / img_filename))
                                _img_counter[0] += 1
                                token = f"[[img:images/{img_filename}]]"
                                log.info(
                                    f"PDF image extracted: {img_filename} "
                                    f"({w:.0f}x{h:.0f} pt)"
                                )
                                pending_img_tokens.append((token, by0))
                            except Exception as exc:
                                log.debug(f"Image extract failed p{page_num}: {exc}")
                    continue

                if btype != 0:  # Skip other non-text blocks
                    continue

                for line in block.get("lines", []):
                    # Reconstruct line with super/subscript → LaTeX conversion
                    line_str = self._spans_to_text(line.get("spans", []))
                    stripped = line_str.strip()
                    if not stripped:
                        raw_lines.append(("", 0.0, 0.0))
                        continue

                    # Check highlight overlap (only when highlights exist)
                    bbox = line.get("bbox")
                    x1 = bbox[2] if bbox else 0.0
                    y0 = bbox[1] if bbox else 0.0

                    if highlight_rects and bbox and self._is_highlighted(bbox, highlight_rects):
                        # Convert wrong/normal marker to correct marker
                        if stripped.startswith("="):
                            # e.g., "= Romantizm" -> "+ Romantizm"
                            # Replace first occurrence of '=' with '+'
                            line_str = line_str.replace("=", "+", 1)
                            log.info(f"Highlight detected! Converted '=' to '+' for option: {stripped}")
                        elif re.match(r"^[a-fA-F][\.\)]\s*", stripped):
                            # e.g., "A) Romantizm" -> "#A) Romantizm"
                            if not stripped.startswith("#"):
                                match = re.match(r"^([a-fA-F][\.\)])", line_str)
                                if match:
                                    prefix = match.group(1)
                                    line_str = line_str.replace(prefix, f"#{prefix}", 1)
                                    log.info(f"Highlight detected! Added '#' for ABC option: {stripped}")
                        else:
                            # e.g., "Romantizm" (Blocks format plain option) -> "#Romantizm"
                            is_question = (
                                stripped.startswith("?") or
                                re.match(r"^\d+[\.\)]", stripped)
                            )
                            if not is_question and not stripped.startswith("#") and not stripped.startswith("+"):
                                leading_spaces = len(line_str) - len(line_str.lstrip())
                                line_str = line_str[:leading_spaces] + "#" + line_str[leading_spaces:]
                                log.info(f"Highlight detected! Added '#' for blocks option: {stripped}")

                    raw_lines.append((line_str, x1, y0))

            # Merge pending image tokens into raw_lines at the correct position.
            # Each token is inserted before the first text line whose y0 exceeds
            # the image's y0, so the token ends up between the question text and
            # its options (matching the visual layout in the PDF).
            for img_token, img_y0 in pending_img_tokens:
                insert_at = len(raw_lines)
                for i, (txt, _x1, ty0) in enumerate(raw_lines):
                    if ty0 > img_y0 and ty0 > 0:
                        insert_at = i
                        break
                raw_lines.insert(insert_at, (img_token, 0.0, img_y0))

            # Join lines that wrapped at the right margin.
            # When a line reaches the right margin (x1 > ~84% of page width),
            # the next non-empty line is its continuation — unless the next line
            # begins with words already at the end of the previous line (which
            # signals two separate options that happen to share vocabulary).
            wrap_threshold = page.rect.width * 0.84
            lines_text: list[str] = []
            prev_x1 = 0.0
            for text, x1, _y0 in raw_lines:
                if not text.strip():
                    prev_x1 = 0.0
                    continue
                # Image tokens are never joined with adjacent text
                if text.strip().startswith("[[img:"):
                    lines_text.append(text)
                    prev_x1 = 0.0
                    continue
                if prev_x1 > wrap_threshold and lines_text:
                    prev_stripped = lines_text[-1].strip()
                    cand_stripped = text.strip()
                    # Never join onto a question line, image token, or numbered question
                    is_question_line = (
                        prev_stripped.startswith("?")
                        or prev_stripped.startswith("[[img:")
                        or bool(re.match(r"^\d+[\.\)]", prev_stripped))
                    )
                    # A genuine wrapped continuation is a sentence fragment — it
                    # never starts a fresh question/option. If the candidate line
                    # itself opens with a test marker (?, =, +) or a numbered
                    # question, it's a NEW item, not a continuation of the long
                    # previous line; joining would glue two options/questions
                    # into one (losing the marker boundary the parser relies on).
                    # Note: require only the marker char itself (no trailing space)
                    # because some PDFs emit "=OptionText" without a space.
                    cand_starts_new_item = bool(re.match(r"^[?+=]", cand_stripped)) or bool(
                        re.match(r"^\d+[\.\)]", cand_stripped)
                    )
                    if (
                        not is_question_line
                        and not cand_starts_new_item
                        and self._is_wrapped_continuation(lines_text[-1], text)
                    ):
                        lines_text[-1] = lines_text[-1].rstrip() + " " + text.lstrip()
                        prev_x1 = x1
                        continue
                lines_text.append(text)
                prev_x1 = x1

            page_text = "\n".join(lines_text)

            # Matritsalarni geometrik tarzda tiklash: PDF'da 2 o'lchovli
            # to'r ko'rinishida joylashgan ko'p qatorli matritsalar oddiy
            # qator-asosli matn ko'rinishida tartibsiz ketma-ketlikka
            # aylanib qoladi — bu yerda ularning asl qator/ustun tartibini
            # belgi-koordinatalari orqali tiklab, "(1 1; 1 1)" ko'rinishidagi
            # aniq, izchil yozuvga keltiramiz.
            try:
                fixed_text, matrix_report = fix_matrices_in_text(page, page_text)
                for entry in matrix_report:
                    log.debug(f"  Matritsa: {entry}")
                page_text = fixed_text
            except Exception as e:
                log.debug(f"Matritsani tiklashda xatolik (o'tkazib yuborildi): {e}")

            # Vektor-strelka (U+20D7) nuqsonlarini tuzatish: ba'zi PDF'larda
            # $\vec{a}$ kabi vektor belgilari strelka aksentini harfdan
            # ALOHIDA glif sifatida saqlaydi — natijada strelka boshqa
            # qatorga "yetim" bo'lib o'tib ketadi yoki bir necha marta
            # takrorlanadi. Bu yerda ularni asl harfiga ulab, bo'linib
            # ketgan qatorlarni qaytadan birlashtiramiz.
            try:
                fixed_text, arrow_report = fix_vector_arrows(page, page_text)
                for entry in arrow_report:
                    log.debug(f"  Vektor strelkasi: {entry}")
                page_text = fixed_text
            except Exception as e:
                log.debug(f"Vektor strelkasini tiklashda xatolik (o'tkazib yuborildi): {e}")

            return page_text

        except Exception as e:
            log.warning(f"Error parsing page structured text: {e}")
            return page.get_text("text")
