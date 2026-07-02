"""
Core data models for the PDF test parser.

All domain objects are defined here using Pydantic for validation
and dataclasses for lightweight intermediate representations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, field_validator, model_validator


# ---------------------------------------------------------------------------
# Intermediate (raw) models — used during parsing before validation
# ---------------------------------------------------------------------------


class ParserState(str, Enum):
    """States for the state-machine parser."""

    WAITING_QUESTION = "WAITING_QUESTION"
    READING_OPTIONS = "READING_OPTIONS"


@dataclass
class RawOption:
    """A single answer option as parsed from raw text."""

    text: str
    is_correct: bool = False
    images: List[str] = field(default_factory=list)


@dataclass
class RawQuestion:
    """Intermediate representation of a question before validation."""

    question_text: str = ""
    options: List[RawOption] = field(default_factory=list)
    line_start: int = 0  # For error reporting
    warnings: List[str] = field(default_factory=list)
    images: List[str] = field(default_factory=list)

    @property
    def correct_count(self) -> int:
        return sum(1 for o in self.options if o.is_correct)

    @property
    def is_potentially_valid(self) -> bool:
        return bool(self.question_text.strip()) and len(self.options) >= 2


# ---------------------------------------------------------------------------
# Validated domain model
# ---------------------------------------------------------------------------


class ParsedQuestion(BaseModel):
    """
    A fully parsed and validated question.

    Fields are intentionally short for compact JSON output.
    """

    q: str  # question text
    o: List[str]  # options list
    c: int  # correct answer index (0-based)
    img: List[str] = []  # image paths associated with the question

    @field_validator("q")
    @classmethod
    def question_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Question text cannot be empty.")
        return v

    @field_validator("o")
    @classmethod
    def options_valid(cls, v: List[str]) -> List[str]:
        cleaned = [opt.strip() for opt in v if opt.strip()]
        if len(cleaned) < 2:
            raise ValueError("At least 2 non-empty options are required.")
        if len(cleaned) > 6:
            raise ValueError("Maximum 6 options allowed.")
        return cleaned

    @model_validator(mode="after")
    def correct_index_in_range(self) -> "ParsedQuestion":
        if not (-1 <= self.c < len(self.o)):
            raise ValueError(
                f"Correct index {self.c} is out of range for {len(self.o)} options."
            )
        return self

    class Config:
        frozen = True  # immutable after validation


# ---------------------------------------------------------------------------
# Validation result wrapper
# ---------------------------------------------------------------------------


class ValidationResult(BaseModel):
    """Result of validating a single raw question."""

    question: Optional[ParsedQuestion] = None
    is_valid: bool = False
    warnings: List[str] = []
    errors: List[str] = []
    raw_images: List[str] = []
    source_line: int = 0


# ---------------------------------------------------------------------------
# Parsing statistics
# ---------------------------------------------------------------------------


class ParsingStats(BaseModel):
    """Aggregated statistics from a full parsing run."""

    total_raw: int = 0
    total_valid: int = 0
    total_invalid: int = 0
    total_warnings: int = 0
    total_duplicates: int = 0
    pages_processed: int = 0
    characters_processed: int = 0
    duration_seconds: float = 0.0
    filename: str = ""

    @property
    def success_rate(self) -> float:
        if self.total_raw == 0:
            return 0.0
        return round(self.total_valid / self.total_raw * 100, 1)


# ---------------------------------------------------------------------------
# Question model (alias for external use)
# ---------------------------------------------------------------------------

# 'Question' is the public name used throughout the app
Question = ParsedQuestion
