"""
Abstract base extractor.

All concrete extractors (PDF text, OCR, DOCX, …) must implement this
interface.  The rest of the pipeline depends only on this abstraction,
making it trivial to swap or add extraction backends later.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ExtractionResult:
    """
    Output of any extractor.

    `pages` is a list of raw text strings, one per page.
    `full_text` is the concatenated version (lazy property).
    """

    pages: list[str]
    page_count: int
    source_path: Path
    extractor_name: str
    encoding: str = "utf-8"

    @property
    def full_text(self) -> str:
        """Return all pages joined with a newline separator."""
        return "\n".join(self.pages)

    @property
    def character_count(self) -> int:
        return len(self.full_text)

    @property
    def is_empty(self) -> bool:
        return not self.full_text.strip()


class BaseExtractor(ABC):
    """
    Abstract base class for all text extractors.

    Concrete subclasses must implement `extract`.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name of the extractor backend."""
        ...

    @abstractmethod
    def extract(self, path: Path) -> ExtractionResult:
        """
        Extract text from *path* and return an :class:`ExtractionResult`.

        Must not raise — wrap exceptions internally and return an empty
        result with a meaningful error logged.
        """
        ...

    def supports(self, path: Path) -> bool:
        """
        Return True if this extractor can handle the given file.

        Default implementation checks file suffix; override as needed.
        """
        return path.suffix.lower() == ".pdf"

    # ── Shared highlight post-processing ───────────────────────────────

    _CORRECT_MARKER = re.compile(r"^[+#]")
    _OPTION_MARKER  = re.compile(r"^[=+#]")
    # Separator chars: . ) ' “ “ “ « »  (chr() avoids smart-quote substitution)
    _Q_SEP_CHARS = (
        chr(0x2e) + chr(0x29)    # period, close-paren
        + chr(0x27) + chr(0x22)  # ASCII apostrophe, ASCII double-quote
        + chr(0x201c) + chr(0x201d) + chr(0x00ab) + chr(0x00bb)
    )
    _QUESTION_START = re.compile(
        r'^\?|^\d+[\.\)]\s'
        + r'|^\d{2,3}[' + _Q_SEP_CHARS + r']\S',
        re.UNICODE,
    )

    _ABC_CORRECT_STAR = re.compile(r"^\*\s*[a-fA-F][\.\)]")

    # "#a) text" / "# b) text" — explicit ABC correct-answer marker written directly
    # into the document text (as opposed to a decorative highlight).
    _ABC_CORRECT_HASH = re.compile(r"^#\s*[a-fA-F][\.\)]")

    _BLOCKS_SEP_RE = re.compile(r"^[+=]{3,}$")

    @classmethod
    def has_explicit_correct(cls, lines: list[str]) -> bool:
        """Return True if any line already carries an explicit correct marker ('+', '#a)' or '*a)')."""
        return any(
            (
                ln.strip().startswith("+")
                and not cls._BLOCKS_SEP_RE.match(ln.strip())
            )
            or cls._ABC_CORRECT_STAR.match(ln.strip())
            or cls._ABC_CORRECT_HASH.match(ln.strip())
            for ln in lines
        )

    @classmethod
    def fix_all_correct(cls, lines: list[str]) -> list[str]:
        """
        If every option of a question is marked correct (+/#), treat it as
        decorative highlighting and strip the markers back to = / plain.

        Works for Classic (+ / =), ABC (# prefix) and Blocks (# prefix) formats.
        """
        result = list(lines)
        i = 0
        while i < len(result):
            s = result[i].strip()
            if not (s.startswith("?") or cls._QUESTION_START.match(s)):
                i += 1
                continue

            # Collect option indices for this question.
            opt_idx: list[int] = []
            j = i + 1
            while j < len(result):
                s2 = result[j].strip()
                if not s2:
                    j += 1
                    continue
                if s2.startswith("?") or cls._QUESTION_START.match(s2):
                    break
                if cls._BLOCKS_SEP_RE.match(s2):
                    break  # blocks separator marks end of question
                if cls._OPTION_MARKER.match(s2):
                    opt_idx.append(j)
                j += 1

            if opt_idx:
                correct = [k for k in opt_idx
                           if cls._CORRECT_MARKER.match(result[k].strip())]
                # Strip markers only when ALL option-marked lines are correct AND
                # there are at least 2 — a lone # is a genuine correct marker, not decorative.
                if correct and len(correct) == len(opt_idx) and len(correct) >= 2:
                    # All options correct → decorative, strip markers
                    for k in correct:
                        ln = result[k]
                        lead = len(ln) - len(ln.lstrip())
                        s3 = ln.strip()
                        if s3.startswith("+"):
                            result[k] = ln[:lead] + "=" + ln[lead + 1:]
                        elif s3.startswith("#"):
                            result[k] = ln[:lead] + ln[lead + 1:]
            i += 1
        return result
