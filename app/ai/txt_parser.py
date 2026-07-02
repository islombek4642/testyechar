"""
State-machine parser for Classic format TXT files.
Parses ? Question, + Correct answer, and = Wrong answer lines.
"""

from __future__ import annotations

import re
from typing import List, Tuple

from app.models.question import RawOption, RawQuestion
from app.utils.logger import get_logger

log = get_logger(__name__)


class TXTQuizParser:
    """
    State machine parser for TXT quiz formats.
    
    Format:
    ? Question text (multiline supported)
    + Correct option (multiline supported)
    = Wrong option (multiline supported)
    """

    def __init__(self) -> None:
        self._current: RawQuestion | None = None
        self._results: List[RawQuestion] = []
        self._line_number: int = 0

    def parse(self, text: str) -> List[RawQuestion]:
        """
        Parse raw TXT content into a list of RawQuestion objects.
        """
        self._current = None
        self._results = []
        lines = text.split("\n")

        for self._line_number, line in enumerate(lines, start=1):
            stripped = line.strip()
            if not stripped:
                continue

            # Skip comments
            if stripped.startswith("!"):
                continue

            marker = stripped[0]
            content = stripped[1:].strip()

            is_question = marker == "?"
            is_correct = marker == "+"
            is_wrong = marker == "="
            is_option = is_correct or is_wrong

            # Strip extra question marks from question content if multiple are present
            if is_question:
                import re
                q_match = re.match(r"^([\?\s]+)(.*)", stripped)
                if q_match:
                    prefix = q_match.group(1)
                    q_count = prefix.count("?")
                    content = q_match.group(2).strip()
                    # Keep track of warning if needed
                    extra_warning = None
                    if q_count > 1:
                        extra_warning = f"Savol oldida ortiqcha ? belgilari bor edi ({q_count} ta topildi, 1 taga qisqartirildi)."
                else:
                    content = stripped[1:].strip()
                    extra_warning = None

            if is_question:
                self._flush_current()
                self._current = RawQuestion(
                    question_text=content,
                    line_start=self._line_number,
                )
                if extra_warning:
                    self._current.warnings.append(extra_warning)

            elif is_option:
                if self._current is None:
                    # Create placeholder question if option found before question
                    self._current = RawQuestion(
                        question_text="",
                        line_start=self._line_number,
                    )
                self._current.options.append(
                    RawOption(text=content, is_correct=is_correct)
                )

            else:
                # Continuation text (multiline question/option)
                if self._current is not None:
                    self._append_continuation(stripped)

        self._flush_current()
        return self._results

    def _append_continuation(self, text: str) -> None:
        if self._current is None:
            return
        if self._current.options:
            last_opt = self._current.options[-1]
            last_opt.text = (last_opt.text + " " + text).strip()
        else:
            self._current.question_text = (self._current.question_text + " " + text).strip()

    def _flush_current(self) -> None:
        if self._current is not None:
            if self._current.question_text.strip() or self._current.options:
                self._results.append(self._current)
            self._current = None


def split_resolved_unresolved(
    questions: List[RawQuestion]
) -> Tuple[List[RawQuestion], List[RawQuestion]]:
    """
    Split raw parsed questions into resolved (has correct options) and 
    unresolved (no correct option index found) questions.
    """
    resolved: List[RawQuestion] = []
    unresolved: List[RawQuestion] = []

    for q in questions:
        if q.correct_count > 0:
            resolved.append(q)
        else:
            unresolved.append(q)

    return resolved, unresolved
