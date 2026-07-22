"""
Legacy binary .doc file extractor.

Extraction strategy (tried in order):
  1. win32com (Word COM automation) — converts .doc → temp .docx, then
     feeds the result through DOCXExtractor for full format detection.
  2. docx2txt  — lightweight plain-text fallback (no tables, no styling).
  3. olefile   — parses the FIB + piece table (Clx/PlcPcd) to decode the
     real document body text, falling back to a crude printable-ASCII
     scan only if the piece table can't be parsed.

Only the first strategy that succeeds is used; the others are skipped.
"""

from __future__ import annotations

import os
import re
import struct
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
        Extract text from the Word binary stream inside the OLE compound
        document by decoding the FIB's piece table (Clx/PlcPcd), which is
        how .doc actually stores body text — falls back to a crude
        printable-ASCII scan only if that parsing fails.
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

                word_doc = ole.openstream("WordDocument").read()
                text = self._extract_doc_text(ole, word_doc)

            if not text.strip():
                return None

            log.info(f"olefile: asosiy matn ajratildi ({len(text):,} belgi, {path.name}).")
            return ExtractionResult(
                pages=[text],
                page_count=1,
                source_path=path,
                extractor_name=self.name,
            )

        except Exception as exc:
            log.warning(f"olefile usuli muvaffaqiyatsiz: {exc}")
            return None

    @staticmethod
    def _extract_doc_text(ole, word_doc: bytes) -> str:
        """
        Decode the document body text via the FIB's piece table, per
        [MS-DOC] 2.5.1 (FibRgFcLcb97), 2.9.177 (Pcd) and the Clx/PlcPcd
        layout. This correctly recovers Unicode text (e.g. Uzbek Latin
        apostrophe letters), which the piece table may store either as
        UTF-16LE or as 1-byte "compressed" (cp1252) runs per piece.

        Falls back to a crude printable-ASCII scan if the FIB/piece table
        can't be parsed (e.g. an unsupported/malformed nFib).
        """
        try:
            flags = struct.unpack_from("<H", word_doc, 10)[0]
            f_which_tbl_stm = (flags >> 9) & 1
            table_stream_name = "1Table" if f_which_tbl_stm else "0Table"
            if not ole.exists(table_stream_name):
                raise ValueError(f"{table_stream_name} stream topilmadi")
            table = ole.openstream(table_stream_name).read()

            # fibRgFcLcbBlob starts right after cbRgFcLcb (offset 152-153);
            # fcClx/lcbClx is entry index 33 in FibRgFcLcb97.
            cb_rg_fc_lcb = struct.unpack_from("<H", word_doc, 152)[0]
            if cb_rg_fc_lcb <= 33:
                raise ValueError("FibRgFcLcb97'da fcClx yozuvi yo'q")
            entry_off = 154 + 33 * 8
            fc_clx, lcb_clx = struct.unpack_from("<II", word_doc, entry_off)
            clx = table[fc_clx:fc_clx + lcb_clx]

            # Clx = zero-or-more Prc blocks (marker 0x01) followed by one
            # Pcdt block (marker 0x02) holding the PlcPcd we need.
            pcdt_data = None
            pos = 0
            while pos < len(clx):
                marker = clx[pos]
                if marker == 1:
                    cb_grpprl = struct.unpack_from("<H", clx, pos + 1)[0]
                    pos += 3 + cb_grpprl
                elif marker == 2:
                    lcb = struct.unpack_from("<I", clx, pos + 1)[0]
                    pcdt_data = clx[pos + 5: pos + 5 + lcb]
                    break
                else:
                    raise ValueError(f"Kutilmagan Clx markeri: {marker}")

            if pcdt_data is None:
                raise ValueError("Pcdt (piece table) topilmadi")

            n_pieces = (len(pcdt_data) - 4) // 12
            cps = struct.unpack_from(f"<{n_pieces + 1}I", pcdt_data)
            pcds_off = 4 * (n_pieces + 1)

            parts: list[str] = []
            for i in range(n_pieces):
                pcd_off = pcds_off + i * 8
                fc_field = struct.unpack_from("<I", pcdt_data, pcd_off + 2)[0]
                f_compressed = bool(fc_field & 0x40000000)
                actual_fc = fc_field & 0x3FFFFFFF
                n_chars = cps[i + 1] - cps[i]

                if f_compressed:
                    byte_off = actual_fc // 2
                    raw = word_doc[byte_off: byte_off + n_chars]
                    parts.append(raw.decode("cp1252", errors="replace"))
                else:
                    byte_off = actual_fc
                    raw = word_doc[byte_off: byte_off + n_chars * 2]
                    parts.append(raw.decode("utf-16-le", errors="replace"))

            text = "".join(parts)
            # Word's internal paragraph/line/cell marks → plain newlines.
            text = text.replace("\x07", "\n")
            text = text.translate({0x0B: "\n", 0x0C: "\n", 0x0D: "\n", 0x00: None})
            return text

        except Exception as exc:
            log.debug(
                f"Piece-table orqali o'qib bo'lmadi ({exc}), "
                "xom ASCII skanerlashga o'tildi."
            )
            chunks = re.findall(rb"[\x20-\x7e\t\r\n]{4,}", word_doc)
            return "\n".join(c.decode("latin-1", errors="replace") for c in chunks)
