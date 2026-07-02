"""
Legacy binary .doc file extractor.

Extraction strategy (tried in order):
  1. win32com (Word COM automation) — converts .doc → temp .docx, then
     feeds the result through DOCXExtractor for full format detection.
  2. docx2txt  — lightweight plain-text fallback (no tables, no styling).
  3. olefile   — raw OLE compound-document text stream extraction.

Only the first strategy that succeeds is used; the others are skipped.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from app.utils.logger import get_logger
from .base import BaseExtractor, ExtractionResult

log = get_logger(__name__)


class DOCExtractor(BaseExtractor):
    """Extractor for legacy binary Word (.doc) files."""

    @property
    def name(self) -> str:
        return "doc-extractor"

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() == ".doc"

    def extract(self, path: Path) -> ExtractionResult:
        log.info(f"[bold cyan]Opening DOC[/]: {path.name}")

        for strategy in (
            self._via_win32com,
            self._via_docx2txt,
            self._via_olefile,
        ):
            result = strategy(path)
            if result is not None:
                return result

        log.error(
            f"Barcha usullar muvaffaqiyatsiz tugadi: {path.name}. "
            "Microsoft Word, docx2txt yoki olefile o'rnatilganligini tekshiring."
        )
        return ExtractionResult(
            pages=[],
            page_count=0,
            source_path=path,
            extractor_name=self.name,
        )

    # ── Strategy 1: win32com ────────────────────────────────────────────

    def _via_win32com(self, path: Path) -> ExtractionResult | None:
        """
        Open the .doc file via Microsoft Word COM automation,
        save as .docx to a temp file, then reuse DOCXExtractor.
        """
        try:
            import win32com.client
        except ImportError:
            log.debug("win32com mavjud emas, keyingi usulga o'tilmoqda.")
            return None

        tmp_path: str | None = None
        word = None
        doc = None
        try:
            word = win32com.client.Dispatch("Word.Application")
            word.Visible = False
            word.DisplayAlerts = False

            abs_path = str(path.resolve())
            doc = word.Documents.Open(
                abs_path,
                ConfirmConversions=False,
                ReadOnly=True,
                AddToRecentFiles=False,
                Format=0,  # wdOpenFormatAuto
            )

            # Save as .docx (FileFormat 16) to a temp file
            fd, tmp_path = tempfile.mkstemp(suffix=".docx")
            os.close(fd)
            doc.SaveAs2(tmp_path, FileFormat=16)
            doc.Close(SaveChanges=False)

            log.info(f"win32com: .doc → .docx muvaffaqiyatli ({path.name})")

            # Process with DOCXExtractor for full format detection
            from .docx_extractor import DOCXExtractor
            result = DOCXExtractor().extract(Path(tmp_path))

            return ExtractionResult(
                pages=result.pages,
                page_count=result.page_count,
                source_path=path,
                extractor_name=self.name,
            )

        except Exception as exc:
            log.warning(f"win32com usuli muvaffaqiyatsiz: {exc}")
            return None

        finally:
            try:
                if doc is not None:
                    doc.Close(SaveChanges=False)
            except Exception:
                pass
            try:
                if word is not None:
                    word.Quit()
            except Exception:
                pass
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

    # ── Strategy 2: docx2txt ────────────────────────────────────────────

    def _via_docx2txt(self, path: Path) -> ExtractionResult | None:
        """
        Extract plain text via the docx2txt library.
        Works for many .doc files without needing Word installed.
        """
        try:
            import docx2txt
        except ImportError:
            log.debug("docx2txt mavjud emas, keyingi usulga o'tilmoqda.")
            return None

        try:
            text = docx2txt.process(str(path))
            if not text or not text.strip():
                return None

            log.info(f"docx2txt: matn ajratildi ({len(text):,} belgi, {path.name})")
            return ExtractionResult(
                pages=[text],
                page_count=1,
                source_path=path,
                extractor_name=self.name,
            )
        except Exception as exc:
            log.warning(f"docx2txt usuli muvaffaqiyatsiz: {exc}")
            return None

    # ── Strategy 3: olefile ─────────────────────────────────────────────

    def _via_olefile(self, path: Path) -> ExtractionResult | None:
        """
        Extract raw text from the Word binary stream inside the OLE
        compound document.  Only ASCII/Latin-1 text is recovered —
        Cyrillic/Uzbek characters may appear garbled.
        """
        try:
            import olefile
        except ImportError:
            log.debug("olefile mavjud emas.")
            return None

        try:
            if not olefile.isOleFile(str(path)):
                log.warning(f"olefile: {path.name} OLE fayl emas.")
                return None

            with olefile.OleFileIO(str(path)) as ole:
                # The main text stream in .doc is "WordDocument"
                if not ole.exists("WordDocument"):
                    return None

                raw = ole.openstream("WordDocument").read()

            # Very basic: extract printable ASCII sequences of length >= 4
            import re
            chunks = re.findall(rb"[\x20-\x7e\t\r\n]{4,}", raw)
            text = "\n".join(c.decode("latin-1", errors="replace") for c in chunks)

            if not text.strip():
                return None

            log.info(
                f"olefile: asosiy matn ajratildi "
                f"({len(text):,} belgi, {path.name}). "
                "Eslatma: unicode belgilar to'liq saqlanmasligi mumkin."
            )
            return ExtractionResult(
                pages=[text],
                page_count=1,
                source_path=path,
                extractor_name=self.name,
            )

        except Exception as exc:
            log.warning(f"olefile usuli muvaffaqiyatsiz: {exc}")
            return None
