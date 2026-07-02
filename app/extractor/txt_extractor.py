"""
Plain-text (.txt) extractor.

Reads the file as UTF-8 (with fallback to cp1251/latin-1) and returns the
full content as a single page, ready for the existing parser pipeline.
"""

from __future__ import annotations

from pathlib import Path

from app.utils.logger import get_logger
from .base import BaseExtractor, ExtractionResult

log = get_logger(__name__)

_ENCODINGS = ("utf-8-sig", "utf-8", "cp1251", "latin-1")


class TXTExtractor(BaseExtractor):
    """Concrete extractor for plain-text files."""

    @property
    def name(self) -> str:
        return "TXTExtractor"

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() == ".txt"

    def extract(self, path: Path) -> ExtractionResult:
        log.info(f"[bold cyan]Opening TXT[/]: {path.name}")

        text = ""
        used_enc = "utf-8"
        for enc in _ENCODINGS:
            try:
                text = path.read_text(encoding=enc)
                used_enc = enc
                break
            except (UnicodeDecodeError, LookupError):
                continue
        else:
            log.error(f"Could not decode {path.name} with any known encoding.")

        result = ExtractionResult(
            pages=[text],
            page_count=1,
            source_path=path,
            extractor_name=self.name,
            encoding=used_enc,
        )

        log.info(
            f"TXT extraction complete — "
            f"{result.character_count:,} characters (encoding: {used_enc})"
        )

        if result.is_empty:
            log.warning("TXT file appears to be empty.")

        return result
