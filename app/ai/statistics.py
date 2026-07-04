"""
AI Statistics & Cost Estimation.

Aggregates token usage, cost estimates (Standard vs Batch API),
timing metrics, and confidence distributions.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List

from app.ai.confidence import ConfidenceTier
from app.ai.merger import ResolvedQuestion


# ── Claude pricing (USD per 1M tokens, as of 2024) ─────────────────────────
# claude-3-5-sonnet-20241022
PRICING = {
    "claude-sonnet-4-6": {
        "input_per_mtok": 3.00,
        "output_per_mtok": 15.00,
        "batch_discount": 0.50,
    },
    "claude-opus-4-7": {
        "input_per_mtok": 5.00,
        "output_per_mtok": 25.00,
        "batch_discount": 0.50,
    },
    "claude-opus-4-8": {
        "input_per_mtok": 5.00,
        "output_per_mtok": 25.00,
        "batch_discount": 0.50,
    },
    "claude-sonnet-5": {
        "input_per_mtok": 3.00,
        "output_per_mtok": 15.00,
        "batch_discount": 0.50,
    },
    "claude-haiku-4-5": {
        "input_per_mtok": 1.00,
        "output_per_mtok": 5.00,
        "batch_discount": 0.50,
    },
    "claude-3-5-sonnet-20241022": {
        "input_per_mtok": 3.00,
        "output_per_mtok": 15.00,
        "batch_discount": 0.50,
    },
    "claude-3-opus-20240229": {
        "input_per_mtok": 15.00,
        "output_per_mtok": 75.00,
        "batch_discount": 0.50,
    },
    "claude-3-5-haiku-20241022": {
        "input_per_mtok": 0.80,
        "output_per_mtok": 4.00,
        "batch_discount": 0.50,
    },
}

# Token estimation constants
TOKENS_PER_QUESTION_INPUT = 120   # rough estimate per question incl. prompt overhead
TOKENS_PER_QUESTION_OUTPUT = 20   # {"id":N,"c":X,"cf":Y}


@dataclass
class AIStatistics:
    """Aggregated statistics from one AI resolver run."""

    total_questions: int = 0
    already_resolved: int = 0
    sent_to_ai: int = 0
    ai_resolved: int = 0
    failed: int = 0

    # Confidence
    trusted_count: int = 0
    warning_count: int = 0
    manual_review_count: int = 0
    average_confidence: float = 0.0

    # Tokens & cost
    estimated_input_tokens: int = 0
    estimated_output_tokens: int = 0
    estimated_total_tokens: int = 0
    estimated_cost_standard_usd: float = 0.0
    estimated_cost_batch_usd: float = 0.0

    # Timing
    start_time: float = field(default_factory=time.perf_counter)
    end_time: float = 0.0
    duration_seconds: float = 0.0

    # Chunks
    chunk_count: int = 0
    chunk_size: int = 25

    # Model
    model: str = "claude-3-5-sonnet-20241022"
    used_batch_api: bool = False

    # Any warnings
    warnings: List[str] = field(default_factory=list)


def compute_statistics(
    questions: List[ResolvedQuestion],
    already_resolved: int,
    ai_resolved: int,
    failed: int,
    chunk_count: int,
    chunk_size: int,
    model: str,
    used_batch_api: bool,
    start_time: float,
    warnings: List[str] | None = None,
) -> AIStatistics:
    """Build a complete AIStatistics object from a resolved question list."""

    stats = AIStatistics(
        total_questions=len(questions),
        already_resolved=already_resolved,
        sent_to_ai=ai_resolved + failed,
        ai_resolved=ai_resolved,
        failed=failed,
        chunk_count=chunk_count,
        chunk_size=chunk_size,
        model=model,
        used_batch_api=used_batch_api,
        start_time=start_time,
    )
    stats.warnings = warnings or []

    # ── Confidence breakdown ────────────────────────────────────────────
    ai_qs = [q for q in questions if q.source == "ai" and q.c != -1]
    stats.trusted_count = sum(1 for q in ai_qs if q.tier == ConfidenceTier.TRUSTED.value)
    stats.warning_count = sum(1 for q in ai_qs if q.tier == ConfidenceTier.WARNING.value)
    stats.manual_review_count = sum(1 for q in ai_qs if q.tier == ConfidenceTier.MANUAL_REVIEW.value)

    if ai_qs:
        stats.average_confidence = round(sum(q.cf for q in ai_qs) / len(ai_qs), 3)

    # ── Token estimation ────────────────────────────────────────────────
    n = stats.sent_to_ai
    stats.estimated_input_tokens = n * TOKENS_PER_QUESTION_INPUT
    stats.estimated_output_tokens = n * TOKENS_PER_QUESTION_OUTPUT
    stats.estimated_total_tokens = stats.estimated_input_tokens + stats.estimated_output_tokens

    # ── Cost estimation ─────────────────────────────────────────────────
    pricing = PRICING.get(model, PRICING["claude-3-5-sonnet-20241022"])
    in_cost = (stats.estimated_input_tokens / 1_000_000) * pricing["input_per_mtok"]
    out_cost = (stats.estimated_output_tokens / 1_000_000) * pricing["output_per_mtok"]
    standard_cost = in_cost + out_cost
    stats.estimated_cost_standard_usd = round(standard_cost, 6)
    stats.estimated_cost_batch_usd = round(standard_cost * (1 - pricing["batch_discount"]), 6)

    # ── Timing ──────────────────────────────────────────────────────────
    stats.end_time = time.perf_counter()
    stats.duration_seconds = round(stats.end_time - stats.start_time, 2)

    return stats
