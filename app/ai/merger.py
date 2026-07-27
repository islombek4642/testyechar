"""
Answer Merger.

Safely merges AI-resolved answers back into the original question list,
preserving already-resolved (+) answers untouched.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from app.ai.confidence import ConfidenceClassifier, ConfidenceTier
from app.ai.validator import AIAnswer
from app.models.question import RawOption, RawQuestion
from app.utils.logger import get_logger

log = get_logger(__name__)


class ResolvedQuestion(BaseModel):
    """Final merged question with confidence metadata."""

    q: str
    o: List[str]
    c: int  # correct answer index (0-based), -1 if unresolved
    cf: float = Field(default=1.0, description="Confidence: 1.0 for manual, AI score otherwise")
    source: str = Field(default="manual", description="'manual' or 'ai'")
    tier: str = Field(default="TRUSTED", description="Confidence tier label")
    searched: bool = Field(default=False, description="Whether web_search was used to resolve this question")


class MergeResult(BaseModel):
    """Aggregated merge output."""

    questions: List[ResolvedQuestion] = Field(default_factory=list)
    total: int = 0
    already_resolved: int = 0
    ai_resolved: int = 0
    failed: int = 0
    merge_warnings: List[str] = Field(default_factory=list)
    images: Dict[int, bytes] = Field(default_factory=dict)
    # key = 0-based index into .questions; value = raw image bytes
    # Populated by AIResolverPipeline; ignored by JSON/TXT exporters.

    model_config = {"arbitrary_types_allowed": True}


class AnswerMerger:
    """
    Merges AI answers back into the full question list.

    - Already-resolved questions (with ``+`` markers) keep ``cf=1.0, source='manual'``.
    - AI-resolved questions get the Claude-reported ``c`` and ``cf``.
    - Failed questions get ``c=-1, cf=0.0``.
    """

    def merge(
        self,
        all_questions: List[RawQuestion],
        resolved_questions: List[RawQuestion],
        unresolved_questions: List[RawQuestion],
        ai_answers: List[AIAnswer],
        question_images: Dict[int, bytes] | None = None,
    ) -> MergeResult:
        """
        Merge resolved + AI answers back into a single ordered list.

        Parameters
        ----------
        all_questions : full ordered list of parsed RawQuestions
        resolved_questions : subset that already had ``+`` markers
        unresolved_questions : subset sent to Claude
        ai_answers : responses from Claude, keyed by ``id`` (1-based into *unresolved_questions*)
        """
        result = MergeResult(total=len(all_questions))

        # Build a lookup: id -> AIAnswer  (id is 1-based into unresolved list)
        ai_map: Dict[int, AIAnswer] = {a.id: a for a in ai_answers}

        # Build sets for fast membership
        resolved_set = set(id(q) for q in resolved_questions)
        unresolved_list = list(unresolved_questions)  # ordered

        unresolved_idx = 0  # pointer walking unresolved_list

        for q in all_questions:
            options_text = [opt.text for opt in q.options if opt.text.strip()]

            if id(q) in resolved_set:
                # ── Already has a correct answer ──────────────────────────
                correct_index = self._find_correct_index(q)
                rq = ResolvedQuestion(
                    q=q.question_text,
                    o=options_text,
                    c=correct_index,
                    cf=1.0,
                    source="manual",
                    tier=ConfidenceTier.TRUSTED.value,
                )
                result.questions.append(rq)
                result.already_resolved += 1

            else:
                # ── Needs AI resolution ───────────────────────────────────
                unresolved_idx += 1
                ai_answer = ai_map.get(unresolved_idx)

                if ai_answer is not None and ai_answer.c != -1:
                    # Validate the returned index
                    if 0 <= ai_answer.c < len(options_text):
                        tier = ConfidenceClassifier.classify(ai_answer.cf)
                        rq = ResolvedQuestion(
                            q=q.question_text,
                            o=options_text,
                            c=ai_answer.c,
                            cf=ai_answer.cf,
                            source="ai",
                            tier=tier.value,
                            searched=ai_answer.s,
                        )
                        result.questions.append(rq)
                        result.ai_resolved += 1
                    else:
                        result.merge_warnings.append(
                            f"AI javob indeksi noto'g'ri: savol «{q.question_text[:60]}…», "
                            f"indeks={ai_answer.c}, variantlar soni={len(options_text)}"
                        )
                        rq = ResolvedQuestion(
                            q=q.question_text,
                            o=options_text,
                            c=-1,
                            cf=0.0,
                            source="ai",
                            tier=ConfidenceTier.MANUAL_REVIEW.value,
                        )
                        result.questions.append(rq)
                        result.failed += 1
                else:
                    # AI couldn't resolve
                    rq = ResolvedQuestion(
                        q=q.question_text,
                        o=options_text,
                        c=-1,
                        cf=0.0,
                        source="ai",
                        tier=ConfidenceTier.MANUAL_REVIEW.value,
                    )
                    result.questions.append(rq)
                    result.failed += 1

        result.images = question_images or {}
        log.info(
            f"Merge yakunlandi: jami={result.total}, "
            f"avvaldan yechilgan={result.already_resolved}, "
            f"AI yechgan={result.ai_resolved}, "
            f"muvaffaqiyatsiz={result.failed}"
        )
        return result

    @staticmethod
    def _find_correct_index(q: RawQuestion) -> int:
        """Return the 0-based index of the first correct option, or -1."""
        for i, opt in enumerate(q.options):
            if opt.is_correct:
                return i
        return -1
