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

# Cyrillic option-letter scheme used by some Russian test banks in place of
# A) B) C) D) — the four letters map 1:1 onto positions 0-3, same as a-f.
_CYRILLIC_LETTERS = "АБВГДЕ"
# Character class fragment combining Latin a-f/A-F with the Cyrillic set,
# for use inside option-marker regexes.
_OPT_LETTER_CLASS = "A-Fa-f" + _CYRILLIC_LETTERS + _CYRILLIC_LETTERS.lower()


def _letter_to_index(letter: str) -> int:
    """Map a Latin (A-F) or Cyrillic (А-Е) option letter to a 0-based index."""
    upper = letter.upper()
    if upper in _CYRILLIC_LETTERS:
        return _CYRILLIC_LETTERS.index(upper)
    return ord(upper) - ord("A")


# Section/part header lines ("ЧАСТЬ 3. Вопросы 74, 75: ...", "Часть 4. Вопросы
# 76-94: ...", and even typo'd variants like "ЧАСТ 4. Вопросы 97 - 100 ...")
# that some Russian test banks insert between question groups. They are
# neither a question nor an option and must never be folded into whichever
# question/option happens to precede them as a continuation line.
# "част" + up to 2 more letters (covers "ь", a missing/typo'd "ь", etc.)
# then whitespace + a digit -- the digit requirement is what keeps this
# from also matching ordinary Russian words that start with the same stem
# ("частица", "частный", "частота" ...).
_SECTION_HEADER_RE = re.compile(r"^част[а-яё]{0,2}\s*\d", re.IGNORECASE | re.UNICODE)


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
        r"|правильный\s+ответ"         # Russian: правильный ответ
        r"|ответ"                      # Russian: ответ
        r")\s*:\s*([" + _OPT_LETTER_CLASS + r"])",
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
        self._correct_opt_regex = re.compile(
            r"^[#*+=]\s*([" + _OPT_LETTER_CLASS + r"])[\.\)]\s*(.*)", re.UNICODE
        )

        # Regex for normal option: e.g. "A) Option" or "B. Option" — also
        # accepts the Cyrillic А) Б) В) Г) scheme some Russian test banks use.
        self._normal_opt_regex = re.compile(
            r"^([" + _OPT_LETTER_CLASS + r"])[\.\)]\s*(.*)", re.UNICODE
        )

    def parse(self, lines: List[str]) -> List[RawQuestion]:
        self._state = ParserState.WAITING_QUESTION
        self._current = None
        self._results = []

        for self._line_number, line in enumerate(lines, start=1):
            stripped = line.strip()
            if not stripped:
                continue

            if _SECTION_HEADER_RE.match(stripped):
                log.debug(f"Line {self._line_number}: Skipping section header: {stripped}")
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
                # Normal option match — correct answer can be marked with a
                # leading "#" or a trailing "*" (e.g. "C) Avitaminoz*").
                option_text = n_match.group(2)
                if self._current is None:
                    self._start_new_question("")
                is_correct = False
                if option_text.startswith("#"):
                    option_text = option_text[1:].strip()
                    is_correct = True
                if option_text.rstrip().endswith("*"):
                    option_text = option_text.rstrip()[:-1].rstrip()
                    is_correct = True
                self._add_option(option_text, is_correct=is_correct)
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
                    correct_idx = _letter_to_index(correct_letter)
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
