"""
State-machine parser for Classic format (? / + / = / !).
"""

from __future__ import annotations

import re
from typing import List

from app.models.question import RawOption, RawQuestion
from app.utils.logger import get_logger
from .state_machine import ParserState

_ABC_OPT = re.compile(r"^([a-fA-F])[\.\)]\s*(?![A-ZА-Я]\.)(.*)", re.UNICODE)

# "Toʻgʻri javob: B" — correct-answer line found in some Uzbek test formats.
_CORRECT_ANSWER_LINE = re.compile(
    r"^To.g.ri\s+javob\s*:?\s*([A-Fa-f])\b",
    re.IGNORECASE | re.UNICODE,
)

# Character class for separators that may appear between a question number and its text.
# Built with chr() to avoid smart-quote substitution by the editor: . ) ' " " " « »
_Q_SEP = (
    '[.)'
    + chr(0x27)   # ASCII apostrophe '
    + chr(0x22)   # ASCII double quote "
    + chr(0x201c) # LEFT DOUBLE QUOTATION MARK (U+201C)
    + chr(0x201d) # RIGHT DOUBLE QUOTATION MARK (U+201D)
    + chr(0xab)   # LEFT ANGLE QUOTE «
    + chr(0xbb)   # RIGHT ANGLE QUOTE »
    + ']'
)

# Matches numbered question starts across several non-standard formats:
#   group 1: "1.Q"  "1)Q"  (standard)
#   group 2: "172 .Q"  "17 .Q"  (space before separator)
#   group 3: "291 3.Q"  (outer + inner numbering)
#   group 4: "119Kompetensiya"  "147Kim"  (2-3 digits, no separator, uppercase)
#   group 5: "185 Ta‟lim"  (2-3 digits, space, uppercase letter)
_NUMBERED_Q = re.compile(
    r'^\d+' + _Q_SEP + r'{1,2}\s*(.+)'        # group 1: standard "1.Q"
    r'|^\d{2,3}\s+' + _Q_SEP + r'+\s*(.+)'    # group 2: "172 .Q"
    r'|^\d{2,3}\s+\d+' + _Q_SEP + r'\s*(.+)'  # group 3: "291 3.Q"
    r'|^\d{2,3}([А-ЯЁA-Z].{4,})'              # group 4: "119Kompetensiya"
    r'|^\d{2,3}\s+([А-ЯЁA-Z].{4,})',          # group 5: "185 Ta‟lim"
    re.UNICODE
)

# Matches question text that is ONLY a number/label (no real content).
# Used to detect "? № 9" style placeholders that should merge with the next ? line.
_NUM_ONLY_Q = re.compile(r'^[^\d\w]*\d+[.\s]*$', re.UNICODE)

# Matches "? #A)option" — a ? line that is actually a correct option (typo in source).
_Q_AS_CORRECT_OPT = re.compile(r'^[#*]\s*[a-fA-F][\.\)]\s*.+', re.UNICODE)

# Matches an option whose own text is a numbered sub-list starting at "1."/"1)"
# (e.g. an option spelled out as "1.Range A 2.Range B 3.Range C" across several
# PDF lines, only the first of which carries the "="/"+" marker). When the
# most recently added option starts this way, a later bare "2."/"3." line is
# that option's continuation, not a new numbered question (see _NUMBERED_Q).
_NUMBERED_LIST_OPT_START = re.compile(r'^1' + _Q_SEP + r'\s*\S', re.UNICODE)

log = get_logger(__name__)


class ClassicParser:
    """
    State machine parser for:
    ? Question text
    + Correct answer
    = Wrong answer
    = Wrong answer
    ! Explanation (optional, ignored)
    """

    def __init__(self) -> None:
        self._state = ParserState.WAITING_QUESTION
        self._current: RawQuestion | None = None
        self._results: List[RawQuestion] = []
        self._line_number: int = 0

    def parse(self, lines: List[str]) -> List[RawQuestion]:
        self._state = ParserState.WAITING_QUESTION
        self._current = None
        self._results = []

        for self._line_number, line in enumerate(lines, start=1):
            stripped = line.strip()
            if not stripped:
                continue

            # Skip comments starting with !
            if stripped.startswith("!"):
                log.debug(f"Line {self._line_number}: Skipping comment: {stripped}")
                continue

            marker = stripped[0]
            content = stripped[1:].strip()

            is_question = marker == "?"
            is_correct = marker in ("+", "#", "*")
            is_wrong = marker in ("=", "-")
            is_option = is_correct or is_wrong

            extra_q_warning = None
            if is_question:
                import re
                q_match = re.match(r"^([\?\s]+)(.*)", stripped)
                if q_match:
                    prefix = q_match.group(1)
                    q_count = prefix.count("?")
                    content = q_match.group(2).strip()
                    if q_count > 1:
                        extra_q_warning = f"Savol oldida ortiqcha ? belgilari bor edi ({q_count} ta topildi, 1 taga qisqartirildi)."

            if self._state == ParserState.WAITING_QUESTION:
                if is_question:
                    if not content:
                        continue  # bare ? with no text — stray PDF character, skip
                    self._start_new_question(content)
                    if extra_q_warning and self._current is not None:
                        self._current.warnings.append(extra_q_warning)
                elif is_option:
                    self._start_new_question("")
                    self._add_option(content, is_correct)
                else:
                    num_m = _NUMBERED_Q.match(stripped)
                    if num_m:
                        self._start_new_question(next(g for g in num_m.groups() if g is not None))

            elif self._state == ParserState.READING_OPTIONS:
                if is_question:
                    if not content:
                        continue  # bare ? — stray PDF character, skip
                    # "? #A)option" — option mistakenly marked with ? instead of =
                    if (
                        _Q_AS_CORRECT_OPT.match(content)
                        and self._current is not None
                        and self._current.options
                    ):
                        self._add_option(content, is_correct=True)
                    # Current question has no options yet: either a numeric
                    # placeholder ("? № 9") or a preamble line ("?Choose the
                    # right answer.") that is immediately followed by the real
                    # question on the next ? line.  In both cases, merge rather
                    # than flush so the preamble+question become one item.
                    elif (
                        self._current is not None
                        and not self._current.options
                    ):
                        if _NUM_ONLY_Q.match(self._current.question_text):
                            self._current.question_text = content
                        else:
                            self._current.question_text = (
                                self._current.question_text.rstrip() + " " + content
                            ).strip()
                    else:
                        self._flush_current()
                        self._start_new_question(content)
                    if extra_q_warning and self._current is not None:
                        self._current.warnings.append(extra_q_warning)
                elif is_option:
                    self._add_option(content, is_correct)
                else:
                    # ABC-style letter option used in classic context: "a) text"
                    # "#" immediately after the letter-marker (or after space) flags the correct answer.
                    abc_m = _ABC_OPT.match(stripped)
                    if abc_m:
                        opt_text = abc_m.group(2).strip()
                        is_abc_correct = opt_text.startswith('#')
                        if is_abc_correct:
                            opt_text = opt_text[1:].strip()
                        self._add_option(opt_text, is_correct=is_abc_correct)
                    else:
                        ca_m = _CORRECT_ANSWER_LINE.match(stripped)
                        if ca_m and self._current is not None and self._current.options:
                            self._mark_correct_by_letter(ca_m.group(1).upper())
                        else:
                            num_m = _NUMBERED_Q.match(stripped)
                            last_opt_is_numbered_list = bool(
                                self._current is not None
                                and self._current.options
                                and _NUMBERED_LIST_OPT_START.match(self._current.options[-1].text.strip())
                            )
                            if (
                                num_m
                                and self._current is not None
                                and self._current.options
                                and not last_opt_is_numbered_list
                            ):
                                self._flush_current()
                                self._start_new_question(next(g for g in num_m.groups() if g is not None))
                            else:
                                self._append_continuation(stripped)

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

    def _mark_correct_by_letter(self, letter: str) -> None:
        """Mark the option starting with the given letter (A–F) as correct."""
        if self._current is None:
            return
        pat = re.compile(rf"^{re.escape(letter)}[\.\)]\s*", re.IGNORECASE)
        for opt in self._current.options:
            if pat.match(opt.text):
                opt.is_correct = True
                return

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
