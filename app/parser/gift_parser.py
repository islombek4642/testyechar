"""
State-machine parser for GIFT format.

GIFT (General Import Format Technology) is used by Moodle and similar platforms.
Each question is plain text followed by a { } block containing options.

Format:
    Question text here
    {
    = Correct answer
    ~ Wrong option 1
    ~ Wrong option 2
    ~ Wrong option 3
    }

Variants handled:
  - { on its own line or appended to the end of the question line
  - Leading/trailing whitespace around = and ~ markers
  - Multi-line question text (lines before {)
  - Multi-line option text (continuation lines inside the block)
"""

from __future__ import annotations

from typing import List

from app.models.question import RawOption, RawQuestion
from app.utils.logger import get_logger

log = get_logger(__name__)


class GIFTParser:
    """
    State-machine parser for GIFT-style { = ~ } format.
    """

    def __init__(self) -> None:
        self._current: RawQuestion | None = None
        self._results: List[RawQuestion] = []
        self._line_number: int = 0
        self._in_block: bool = False

    def parse(self, lines: List[str]) -> List[RawQuestion]:
        self._current = None
        self._results = []
        self._in_block = False

        for self._line_number, line in enumerate(lines, start=1):
            stripped = line.strip()
            if not stripped:
                continue

            # ── Any line starting with { (outside block) ────────────────
            # Handles: "{" alone, "question text {", "{=option", "{~option"
            if stripped.startswith("{") and not self._in_block:
                if self._current is None:
                    self._current = RawQuestion(line_start=self._line_number)

                # Case A: question text ends with { → "Question text {"
                if not stripped.startswith("{=") and not stripped.startswith("{~"):
                    question_part = stripped[:-1].strip() if stripped.endswith("{") else ""
                    if not question_part and stripped != "{":
                        # Unknown inline content, treat as question text
                        if self._current.question_text:
                            self._current.question_text += " " + stripped
                        else:
                            self._current.question_text = stripped
                        continue
                    self._in_block = True
                    if question_part:
                        if self._current.question_text:
                            self._current.question_text += " " + question_part
                        else:
                            self._current.question_text = question_part
                    continue

                # Case B: "{=option" or "{~option[}]" — first option on brace line
                self._in_block = True
                inner = stripped[1:]  # strip leading {
                # Check if block also closes on this line
                if inner.endswith("}"):
                    inner = inner[:-1].rstrip()
                    closes = True
                else:
                    closes = False
                inner = inner.strip()
                if inner.startswith("="):
                    self._current.options.append(
                        RawOption(text=inner[1:].strip(), is_correct=True)
                    )
                elif inner.startswith("~"):
                    self._current.options.append(
                        RawOption(text=inner[1:].strip(), is_correct=False)
                    )
                if closes:
                    self._in_block = False
                    self._flush_current()
                continue

            # ── Closing brace — flush question ──────────────────────────
            if stripped == "}" and self._in_block:
                self._in_block = False
                self._flush_current()
                continue

            # ── Inside option block ─────────────────────────────────────
            if self._in_block:
                if self._current is None:
                    self._current = RawQuestion(line_start=self._line_number)

                # Option line with } embedded at the end (e.g. "~ answer }")
                # Treat everything before } as the option text, then close the block.
                if stripped.endswith("}") and stripped != "}":
                    content = stripped[:-1].rstrip()
                    marker, text = self._parse_option_marker(content)
                    if marker == "=":
                        self._current.options.append(RawOption(text=text, is_correct=True))
                    elif marker == "~":
                        self._current.options.append(RawOption(text=text, is_correct=False))
                    elif content and self._current.options:
                        self._current.options[-1].text += " " + content
                    self._in_block = False
                    self._flush_current()
                    continue

                marker, text = self._parse_option_marker(stripped)
                if marker == "=":
                    self._current.options.append(RawOption(text=text, is_correct=True))
                elif marker == "~":
                    self._current.options.append(RawOption(text=text, is_correct=False))
                else:
                    # Continuation of the previous option's text
                    if self._current.options:
                        self._current.options[-1].text += " " + stripped
                continue

            # ── Outside block — accumulate question text ─────────────────
            if self._current is None:
                self._current = RawQuestion(line_start=self._line_number)
            if self._current.question_text:
                self._current.question_text += " " + stripped
            else:
                self._current.question_text = stripped

        # Flush any unclosed block at end of file
        if self._in_block:
            log.warning(
                f"GIFT: fayl oxirida yopilmagan '{{' blok topildi "
                f"(qator {self._line_number}). Qisman savol saqlanadi."
            )
        self._flush_current()

        log.info(f"GIFT parser: {len(self._results)} ta savol aniqlandi.")
        return self._results

    @staticmethod
    def _parse_option_marker(s: str) -> tuple[str, str]:
        """
        Parse a GIFT option line and return (marker, text).

        Handles:
          "= text"  → ("=", "text")   correct answer
          "~ text"  → ("~", "text")   wrong answer
          "+~ text" → ("~", "text")   wrong with partial credit (treated as wrong)
          "+%N% t"  → ("=", "t")      weighted correct (treated as correct)
          other     → ("", s)         continuation / unknown
        """
        import re
        s = s.strip()
        if s.startswith("="):
            return "=", s[1:].strip()
        if s.startswith("~"):
            return "~", s[1:].strip()
        # "+~ text" — negative-weight wrong answer
        if s.startswith("+~"):
            return "~", s[2:].strip()
        # "+%N% text" — weighted correct answer
        m = re.match(r"^\+%[\d.+-]+%\s*(.*)", s)
        if m:
            return "=", m.group(1).strip()
        return "", s

    def _flush_current(self) -> None:
        if self._current is not None:
            self._current.options = [
                o for o in self._current.options if o.text.strip()
            ]
            if self._current.question_text.strip() or self._current.options:
                self._results.append(self._current)
            self._current = None
