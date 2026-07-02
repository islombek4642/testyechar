"""
State-machine parser for Blocks format (separated by +++ and ===).
"""

from __future__ import annotations

import re
from typing import List

from app.models.question import RawOption, RawQuestion
from app.utils.logger import get_logger
from .state_machine import ParserState

log = get_logger(__name__)


class BlocksParser:
    """
    State machine parser for separator-based tests:
    Savol matni shu yerda
    ======
    #To'g'ri javob
    ======
    Noto'g'ri javob 1
    ======
    Noto'g'ri javob 2
    ++++++
    Navbatdagi savol matni
    """

    def __init__(self) -> None:
        self._current: RawQuestion | None = None
        self._results: List[RawQuestion] = []
        self._line_number: int = 0
        self._reading_question_text = True

    def _is_header_line(self, line: str, is_last_few: bool) -> bool:
        stripped = line.strip()
        if not stripped:
            return False
            
        # 1. Signature lines containing 3 or more underscores (always header)
        if "___" in stripped:
            return True
            
        lower_line = stripped.lower()
        
        # 2. Year lines (short signature date lines, e.g. "2025 yil" or "2024-y.")
        if len(stripped) < 30 and (re.search(r"\d{4}\s*-?\s*yil", lower_line) or re.search(r"\d{4}\s*-?\s*y\b", lower_line)):
            return True
            
        # If it is the last line before the separator (the actual question), protect it
        if is_last_few:
            return False

        # 3. ALL-CAPS lines (institutional titles like "O'ZBEKISTON RESPUBLIKASI")
        # Strip punctuation/digits, check if all remaining letters are uppercase.
        bare = re.sub(r"[^a-zA-ZА-Яа-яёЁ]", "", stripped)
        if bare and bare == bare.upper() and len(bare) >= 6 and not stripped.endswith("?"):
            return True

        # 4. Fully-quoted lines that are NOT questions (department / course names)
        if (
            len(stripped) > 6
            and stripped[0] in ('"', '«')
            and stripped[-1] in ('"', '»')
            and not stripped[1:-1].strip().endswith('?')
        ):
            return True

        # 5. Uzbek/Russian administrative header keywords (case-insensitive)
        header_keywords = {
            "tasdiqlayman", "tasdiqlash", "tasdiqladi",
            "kafedra", "mudiri", "dekan", "tuzuvchi",
            "imzo", "sana", "professor", "dotsent", "dosent",
            "assistent", "tasdiqlayman:", "kafedrasi", "semestr",
            "universitet", "universiteti", "universitetining",
            "institut", "instituti", "akademik", "rahbari",
            "boshlig’i", "boshligi", "mudir", "dekani", "fakulteti",
            "prorektori", "rektori", "vazirlik", "respublika",
        }

        # Lines not ending with ‘?’ may be headers if they contain header keywords.
        # No length cap: Uzbek institutional headers can be arbitrarily long.
        if not stripped.endswith("?"):
            words = re.findall(r"[a-z’’ʻа-яё]+", lower_line)
            for word in words:
                # Exact match OR prefix match — handles Uzbek grammatical suffixes,
                # e.g. "kafedrasining" → "kafedra", "fakultetimiz" → "fakulteti".
                if word in header_keywords or any(
                    word.startswith(kw) for kw in header_keywords
                ):
                    return True

            # Common title/header phrases
            phrases = [
                "test savollari", "test topshiriqlari", "fanidan test",
                "kafedra mudiri", "o’quv yili", "oquv yili", "tasdiq qilaman",
                "nazorat testlari", "oraliq nazorat", "yakuniy nazorat",
            ]
            if any(p in lower_line for p in phrases):
                return True

        return False

    def _clean_leading_headers(self, lines: List[str]) -> List[str]:
        # Find the index of the first option separator (===)
        first_opt_sep_idx = -1
        for idx, line in enumerate(lines):
            stripped = line.strip()
            if len(stripped) >= 3 and all(c == "=" for c in stripped):
                first_opt_sep_idx = idx
                break
                
        if first_opt_sep_idx == -1:
            return lines
            
        # Find indices of non-empty lines before the first separator
        non_empty_indices = []
        for idx in range(first_opt_sep_idx):
            if lines[idx].strip():
                non_empty_indices.append(idx)
                
        # Protect the very last non-empty line (this is definitely the question text)
        last_few_indices = set(non_empty_indices[-1:]) if non_empty_indices else set()
            
        # We only clean up lines before the first separator
        cleaned_lines = []
        for idx, line in enumerate(lines):
            if idx < first_opt_sep_idx:
                is_last_few = idx in last_few_indices
                # If it's a header line, skip it
                if self._is_header_line(line, is_last_few):
                    log.info(f"Skipping leading header line: {line.strip()}")
                    continue
            cleaned_lines.append(line)
            
        return cleaned_lines

    # Footer-specific patterns: "Title: Name" signatures at document end
    _FOOTER_SIG_RE = re.compile(
        r"\bo['ʻ]qituvchi(si)?\b"
        r"|kafedra(\s+mudiri)?"
        r"|\bmudiri\s*:"
        r"|\btuzuvchi\b"
        r"|\bdekan[ia]?\b"
        r"|\bimzo\b"
        r"|\bsana\b"
        r"|\bprof\.\s"
        r"|\b(dotsent|dosent)\b",
        re.IGNORECASE | re.UNICODE,
    )

    def _clean_trailing_footers(self, lines: List[str]) -> List[str]:
        """Remove trailing footer/signature lines that appear after the last option."""
        i = len(lines) - 1
        while i >= 0:
            stripped = lines[i].strip()
            is_sep = len(stripped) >= 3 and (
                all(c == "+" for c in stripped) or all(c == "=" for c in stripped)
            )
            if is_sep:
                break
            is_footer = self._is_header_line(stripped, False) or (
                len(stripped) < 100
                and not stripped.endswith("?")
                and bool(self._FOOTER_SIG_RE.search(stripped))
            )
            if is_footer:
                i -= 1
            else:
                break
        return lines[: i + 1]

    # Matches "++++ Some question text" — separator fused with question on same line
    _FUSED_Q_SEP = re.compile(r"^(\+{3,})\s+(.+)", re.DOTALL)

    # Quote characters that may precede a "+"/"#" correctness marker, e.g. '"+Answer" text'
    _QUOTE_CHARS = ('"', "'", "“", "‘", "«", "„")

    @classmethod
    def _extract_correct_marker(cls, stripped: str) -> tuple[bool, str]:
        """Detect a leading '#'/'+' correctness marker, optionally placed right
        after an opening quote character, and strip it from the text.

        Returns (is_correct, cleaned_text).
        """
        if stripped.startswith(("#", "+", "*")):
            return True, stripped[1:].strip()
        if len(stripped) > 1 and stripped[0] in cls._QUOTE_CHARS and stripped[1] in ("#", "+", "*"):
            return True, stripped[0] + stripped[2:]
        return False, stripped

    def parse(self, lines: List[str]) -> List[RawQuestion]:
        lines = self._clean_leading_headers(lines)
        lines = self._clean_trailing_footers(lines)
        self._current = None
        self._results = []
        self._reading_question_text = True

        for self._line_number, line in enumerate(lines, start=1):
            stripped = line.strip()
            if not stripped:
                continue

            # ── Check for separators ────────────────────────────────────
            # Question separator: +++ (at least 3 pluses)
            is_q_sep = len(stripped) >= 3 and all(c == "+" for c in stripped)

            # Handle "++++<space>Question text" fused on one line
            fused_m = None
            if not is_q_sep:
                fused_m = self._FUSED_Q_SEP.match(stripped)
                if fused_m and all(c == "+" for c in fused_m.group(1)):
                    is_q_sep = True

            # Option separator: === (at least 3 equals)
            is_opt_sep = len(stripped) >= 3 and all(c == "=" for c in stripped)

            if is_q_sep:
                # Flush the current question and prepare for a new one
                self._flush_current()
                self._reading_question_text = True
                if fused_m:
                    # The fused remainder is the start of the next question
                    remainder = fused_m.group(2).strip()
                    if remainder:
                        self._start_new_question(remainder)
                continue

            if is_opt_sep:
                # We've finished reading the question text or a previous option,
                # and are now moving to the next option
                if self._current is None:
                    # Start a blank question if we hit an option separator first
                    self._start_new_question("")
                self._reading_question_text = False
                # Add an empty option placeholder to start appending to it next
                self._current.options.append(RawOption(text="", is_correct=False))
                continue

            # ── Handle actual content ────────────────────────────────────
            if self._current is None:
                self._start_new_question("")

            if self._reading_question_text:
                # '#Answer'/'+Answer' directly after question (no ==== separator in between):
                # treat it as the correct option and switch to options phase.
                is_correct, marker_text = self._extract_correct_marker(stripped)
                if is_correct and self._current.question_text:
                    self._current.options.append(
                        RawOption(text=marker_text, is_correct=True)
                    )
                    self._reading_question_text = False
                else:
                    # Normal question text accumulation
                    if self._current.question_text:
                        self._current.question_text += " " + stripped
                    else:
                        self._current.question_text = stripped
            else:
                # Append to the last option
                if self._current.options:
                    last_opt = self._current.options[-1]
                    if not last_opt.text:
                        # First line of the option text — check for correctness prefix
                        # ("#" or "+" both mark the correct answer). A standalone
                        # marker line (e.g. just "+") leaves the text empty for now,
                        # so don't clear is_correct if a later line carries no marker.
                        is_correct, marker_text = self._extract_correct_marker(stripped)
                        if is_correct:
                            last_opt.is_correct = True
                        last_opt.text = marker_text
                    else:
                        last_opt.text += " " + stripped
                else:
                    # Fallback if no options exist yet — add one
                    is_correct, marker_text = self._extract_correct_marker(stripped)
                    self._current.options.append(RawOption(text=marker_text, is_correct=is_correct))

        self._flush_current()
        return self._results

    def _start_new_question(self, text: str) -> None:
        self._current = RawQuestion(
            question_text=text,
            line_start=self._line_number,
        )

    def _flush_current(self) -> None:
        if self._current is not None:
            # Clean up empty placeholder options
            self._current.options = [o for o in self._current.options if o.text.strip()]
            if self._current.question_text.strip() or self._current.options:
                self._results.append(self._current)
            self._current = None
