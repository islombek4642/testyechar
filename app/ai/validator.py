"""
Pydantic schemas and validation for AI-resolved quiz answers.
Verifies structure, indices, and confidence metrics.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class AIAnswer(BaseModel):
    """
    A single resolved answer returned from the AI client.
    """

    id: int = Field(description="The index/ID of the question mapped back from the input.")
    c: int = Field(description="The 0-based index of the resolved correct option, or -1 if unresolved.")
    cf: float = Field(default=0.0, description="The estimated confidence score (0.00 to 1.00).")
    s: bool = Field(default=False, description="Whether the web_search tool was used to verify this specific question.")

    @field_validator("cf")
    @classmethod
    def validate_confidence(cls, v: float) -> float:
        """Ensure confidence is in range [0.0, 1.0]"""
        if not (0.0 <= v <= 1.0):
            # Clamp or fallback safely
            return max(0.0, min(1.0, v))
        return round(v, 2)


class AIAnswerList(BaseModel):
    """
    List of resolved answers, used for Pydantic parsing.
    """

    answers: List[AIAnswer]


class AIValidationReport(BaseModel):
    """
    Consolidated QA report summarizing resolving issues.
    """

    total_resolved: int = 0
    trusted_count: int = 0
    warning_count: int = 0
    manual_review_count: int = 0
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
