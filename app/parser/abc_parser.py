"""
State-machine parser for ABC format (1. A) B) #C) D)).
"""

from __future__ import annotations

import re
from typing import List

from app.models.question import RawOption, RawQuestion
from app.utils.logger import get_logger
from .state_machine import ParserState

log = get_logger(__name__)


class ABCParser:
    """
    State machine parser for standard numbered/lettered tests:
    1. Savol matni shu yerda?
    A) Noto'g'ri javob
    #B) To'g'ri javob
    C) Noto'g'ri javob
    """

    # Explicit correct-answer line in Uzbek or English, e.g.:
    #   "To'g'ri javob: A"  /  "Toʻgʻri javob: B"
    #   "Answer: C"  /  "Correct answer: D"  /  "Correct: B"
    _TOGRI_JAVOB_RE = re.compile(
        r"^(?:"
        r"to['ʻ]?g['ʻ]?ri\s+javob"   # Uzbek: to'g'ri javob / toʻgʻri javob
        r"|correct\s+answer"           # English: correct answer
        r"|correct"                    # English: correct
        r"|answer"                     # English: answer
        r"|right\s+answer"             # English: right answer
        r")\s*:\s*([a-fA-F])",
        re.IGNORECASE | re.UNICODE,
    )

    def __init__(self) -> None:
        self._state = ParserState.WAITING_QUESTION
        self._current: RawQuestion | None = None
        self._results: List[RawQuestion] = []
        self._line_number: int = 0

        # Regex for question: e.g. "1. Savol", "42) Savol", or "333 Savol" (space after number)
        self._q_regex = re.compile(r"^\d+[\.\)\s]\s*(.*)", re.UNICODE)

        # Regex for correct option: "#A) Option", "*B) Option", "+C. Option", "=D) Option"
        self._correct_opt_regex = re.compile(r"^[#*+=]\s*([a-fA-F])[\.\)]\s*(.*)", re.UNICODE)

        # Regex for normal option: e.g. "A) Option" or "B. Option"
        self._normal_opt_regex = re.compile(r"^([a-fA-F])[\.\)]\s*(.*)", re.UNICODE)

    def parse(self, lines: List[str]) -> List[RawQuestion]:
        self._state = ParserState.WAITING_QUESTION
        self._current = None
        self._results = []

        for self._line_number, line in enumerate(lines, start=1):
            stripped = line.strip()
            if not stripped:
                continue

            # Check matching patterns
            q_match = self._q_regex.match(stripped)
            c_match = self._correct_opt_regex.match(stripped)
            n_match = self._normal_opt_regex.match(stripped)

            if q_match:
                # Numbered question starts
                self._flush_current()
                self._start_new_question(q_match.group(1))
            elif c_match:
                # Correct option match
                option_text = c_match.group(2)
                if self._current is None:
                    self._start_new_question("")
                self._add_option(option_text, is_correct=True)
            elif n_match:
                # Normal option match — check if text starts with # (correct answer marker)
                option_text = n_match.group(2)
                if self._current is None:
                    self._start_new_question("")
                if option_text.startswith("#"):
                    self._add_option(option_text.lstrip("#").strip(), is_correct=True)
                else:
                    self._add_option(option_text, is_correct=False)
            elif (stripped.startswith("+ ") or stripped.startswith("* ")) and self._current is not None:
                self._add_option(stripped[2:].strip(), is_correct=True)
            elif stripped.startswith("= ") and self._current is not None:
                # Classic wrong marker without letter: "= option text"
                self._add_option(stripped[2:].strip(), is_correct=False)
            else:
                # "To'g'ri javob: A" — explicit correct-answer indicator
                togri_m = self._TOGRI_JAVOB_RE.match(stripped)
                if togri_m and self._current is not None:
                    correct_letter = togri_m.group(1).upper()
                    correct_idx = ord(correct_letter) - ord('A')
                    if 0 <= correct_idx < len(self._current.options):
                        for opt in self._current.options:
                            opt.is_correct = False
                        self._current.options[correct_idx].is_correct = True
                    else:
                        log.warning(
                            f"Line {self._line_number}: "
                            f"To'g'ri javob '{correct_letter}' — variant topilmadi"
                        )
                elif self._current is not None:
                    self._append_continuation(stripped)
                else:
                    log.debug(f"Line {self._line_number}: Ignoring random line: {stripped}")

        self._flush_current()
        return self._results

    def _start_new_question(self, text: str) -> None:
        self._current = RawQuestion(
            question_text=text,
            line_start=self._line_number,
        )
        self._state = ParserState.READING_OPTIONS

    def _add_option(self, text: str, is_correct: bool) -> None:
        if self._current is not None:
            self._current.options.append(RawOption(text=text, is_correct=is_correct))

    def _append_continuation(self, text: str) -> None:
        if self._current is None:
            return
        if self._current.options:
            last_opt = self._current.options[-1]
            last_opt.text = last_opt.text + " " + text
        else:
            self._current.question_text += " " + text

    def _flush_current(self) -> None:
        if self._current is not None:
            if self._current.question_text.strip() or self._current.options:
                self._results.append(self._current)
            self._current = None
