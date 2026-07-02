"""
Parser for multi-column DOCX table Q&A format.

Supported layouts:
  Layout A: col[0]=question, col[1+]=answers
            Correct answer: '*'-prefixed cell OR first column (position-based).
  Layout B: col[0]=number or mostly empty, col[1]=question, col[2+]=answers
            Detected when col[0] fill ratio < 50% across data rows,
            OR col[0] contains sequential integers in 3+ rows.

Row handling rules:
  - Empty rows or rows with only 1 non-empty cell              -> skipped
  - Header row (contains column label keywords like "savol")   -> skipped
  - Merged header row (all cells identical)                    -> skipped
  - Layout A, col[0] empty but col[1+] non-empty              -> skipped (page-break leftover)
  - Layout B, col[1] empty                                     -> skipped (no question text)
  - Rows with question but no answers                          -> emitted (validator handles)
"""

from __future__ import annotations

import re
from typing import List

from app.models.question import RawOption, RawQuestion
from app.utils.logger import get_logger

log = get_logger(__name__)

# Matches a cell that contains only a number (optionally followed by a period/space)
_NUM_ONLY = re.compile(r'^\d+\.?\s*$')

# Header row keyword patterns (Uzbek + English + Russian)
_HEADER_KW = re.compile(
    r'\b(?:savol|javob|to[\W_]*g[\W_]*ri|muqobil|question|answer|correct|wrong|option|variant)\b'
    r'|вопрос|ответ|правильн|альтернатив'
    r'|^[№Nn]$|^T/r$|^no\.?$',
    re.IGNORECASE | re.UNICODE,
)


class TableParser:
    """
    Converts multi-column table rows into Classic format lines or RawQuestion objects.

    Input : ``list[list[str]]`` — each inner list is one row's cell texts (already
            deduplicated for merged cells by the DOCX extractor).
    Output: Classic marker lines (``? / + / =``) consumed by ClassicParser,
            or directly parsed ``RawQuestion`` objects.
    """

    # ── Layout & marker detection ────────────────────────────────────────

    @staticmethod
    def detect_layout(rows: list[list[str]]) -> str:
        """
        Return 'B' when col[0] is a number/empty column (question is in col[1]).
        Return 'A' when col[0] is the question column.

        Layout-B indicators (either one is enough):
          1. col[0] has sequential integers across 3+ data rows.
          2. col[0] fill ratio < 50% while col[1] fill ratio > 50% across data rows.
        """
        col0_filled = 0
        col1_filled = 0
        total_data = 0
        nums: list[int] = []

        for row in rows[:60]:
            if not row:
                continue
            non_empty = [c for c in row if c]
            if len(non_empty) <= 1:
                continue
            # Skip obvious header rows from statistics
            if TableParser._is_header_row(row):
                continue

            total_data += 1
            if row[0]:
                col0_filled += 1
                if _NUM_ONLY.match(row[0]):
                    nums.append(int(re.search(r'\d+', row[0]).group()))
            if len(row) > 1 and row[1]:
                col1_filled += 1

        if total_data == 0:
            return 'A'

        # Indicator 1: sequential numbers in col[0]
        if len(nums) >= 3:
            sequential = sum(1 for i in range(1, len(nums)) if nums[i] == nums[i - 1] + 1)
            if sequential >= len(nums) - 1:
                return 'B'

        # Indicator 2: col[0] mostly empty, col[1] mostly filled
        col0_ratio = col0_filled / total_data
        col1_ratio = col1_filled / total_data
        if col0_ratio < 0.5 and col1_ratio > 0.5:
            return 'B'

        return 'A'

    @staticmethod
    def detect_star_marker(rows: list[list[str]]) -> bool:
        """Return True if any non-first cell uses a '*' prefix to flag the correct answer."""
        for row in rows[:30]:
            if len(row) < 2:
                continue
            if any(c.startswith('*') for c in row[1:] if c):
                return True
        return False

    @staticmethod
    def _is_header_row(cells: list[str]) -> bool:
        """
        Return True when the row looks like a table column-label header.

        A header row has all cells short (< 40 chars each) AND at least 2 cells
        match known header keywords (savol, javob, to'g'ri, muqobil, №, question…).
        """
        non_empty = [c for c in cells if c]
        if not non_empty:
            return False
        if any(len(c) >= 40 for c in non_empty):
            return False
        matches = sum(1 for c in non_empty if _HEADER_KW.search(c))
        return matches >= min(2, len(non_empty))

    # ── Conversion ──────────────────────────────────────────────────────

    @classmethod
    def to_classic_lines(cls, rows: list[list[str]]) -> list[str]:
        """
        Convert table rows to Classic marker lines.

        Returns a flat list: '? question', '+ correct', '= wrong', ...

        Algorithm per data row:
          1. Skip empty / single-cell rows and header rows.
          2. Skip merged-header rows (all cells identical, first occurrence only).
          3. Layout A: skip rows where col[0] is empty (page-break fragment).
          4. Layout B: skip rows where col[1] is empty (no question text).
          5. Emit '? question'.
          6. Walk answer cells:
               '*'-prefixed -> '+ text'   (star-marker mode)
               everything else -> collect as wrong candidates
          7. If no '*' found, promote first wrong candidate to '+' (position-based).
        """
        if not rows:
            return []

        layout = cls.detect_layout(rows)
        use_star = cls.detect_star_marker(rows)

        lines: list[str] = []
        merged_header_seen = False

        for row in rows:
            non_empty = [c for c in row if c]

            # Skip empty rows and single-cell rows
            if len(non_empty) <= 1:
                continue

            # Skip table column-label header rows
            if cls._is_header_row(row):
                continue

            # Skip merged header row (all cells share identical text — first time only)
            if not merged_header_seen and len(set(non_empty)) == 1:
                merged_header_seen = True
                continue

            if layout == 'A':
                # Layout A: col[0] is the question column.
                # Skip rows where col[0] is empty (page-break leftover / continuation).
                if not row[0]:
                    continue
                q_text = row[0]
                answer_cells = row[1:]
            else:
                # Layout B: col[0] is number/empty; col[1] is the question column.
                # Skip rows where col[1] is empty (no question text).
                q_text = row[1] if len(row) > 1 else ''
                if not q_text:
                    continue
                answer_cells = row[2:] if len(row) > 2 else []

            lines.append('? ' + q_text)

            # Emit answer options
            correct_found = False
            wrong_candidates: list[str] = []

            for cell in answer_cells:
                if not cell:
                    continue
                if use_star and cell.startswith('*'):
                    lines.append('+ ' + cell[1:].strip())
                    correct_found = True
                else:
                    wrong_candidates.append(cell)

            # Position-based fallback: first wrong candidate becomes the correct answer
            for i, cell in enumerate(wrong_candidates):
                if i == 0 and not correct_found:
                    lines.append('+ ' + cell)
                else:
                    lines.append('= ' + cell)

        q_count = sum(1 for ln in lines if ln.startswith('? '))
        correct_count = sum(1 for ln in lines if ln.startswith('+ '))
        log.info(
            f"TableParser: layout={layout}, star_marker={use_star}, "
            f"{q_count} ta savol, {correct_count} ta to'g'ri javob."
        )
        return lines

    @classmethod
    def parse(cls, rows: list[list[str]]) -> list[RawQuestion]:
        """Parse table rows directly into RawQuestion objects via ClassicParser."""
        from .classic_parser import ClassicParser

        lines = cls.to_classic_lines(rows)
        return ClassicParser().parse(lines)
