"""
AI Statistics & Cost Calculation.

Aggregates real token usage (from Claude API response.usage), cost
(Standard vs Batch API), timing metrics, and confidence distributions.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List

from app.ai.confidence import ConfidenceTier
from app.ai.merger import ResolvedQuestion


# ── Claude pricing (USD per 1M tokens) — only the models the bot's
# Sozlamalar menu lets the admin choose from (bot/handlers.py MODEL_OPTIONS).
PRICING = {
    "claude-opus-5": {
        "input_per_mtok": 5.00,
        "output_per_mtok": 25.00,
        "batch_discount": 0.50,
    },
    "claude-opus-4-8": {
        "input_per_mtok": 5.00,
        "output_per_mtok": 25.00,
        "batch_discount": 0.50,
    },
    "claude-opus-4-7": {
        "input_per_mtok": 5.00,
        "output_per_mtok": 25.00,
        "batch_discount": 0.50,
    },
    # $2/$10 was introductory pricing through 2026-08-31; Anthropic made it
    # the permanent rate instead of reverting to $3/$15 on 2026-09-01
    # (see https://platform.claude.com/docs/en/about-claude/pricing).
    "claude-sonnet-5": {
        "input_per_mtok": 2.00,
        "output_per_mtok": 10.00,
        "batch_discount": 0.50,
    },
}


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
    searched_count: int = 0  # questions Claude verified via web_search

    # Tokens & cost — real usage reported by the Claude API (response.usage),
    # not a heuristic guess.
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_standard_usd: float = 0.0  # what this token count would cost via Standard API
    cost_batch_usd: float = 0.0     # what it costs via Batch API (50% off) — the real bill when used_batch_api is True

    # Timing
    start_time: float = field(default_factory=time.perf_counter)
    end_time: float = 0.0
    duration_seconds: float = 0.0

    # Chunks
    chunk_count: int = 0
    chunk_size: int = 25

    # Model
    model: str = "claude-opus-4-8"
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
    input_tokens: int = 0,
    output_tokens: int = 0,
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
    stats.searched_count = sum(1 for q in ai_qs if q.searched)

    # ── Token usage (real, from Claude API response.usage) ──────────────
    stats.input_tokens = input_tokens
    stats.output_tokens = output_tokens
    stats.total_tokens = input_tokens + output_tokens

    # ── Cost ──────────────────────────────────────────────────────────
    pricing = PRICING.get(model, PRICING["claude-opus-4-8"])
    in_cost = (stats.input_tokens / 1_000_000) * pricing["input_per_mtok"]
    out_cost = (stats.output_tokens / 1_000_000) * pricing["output_per_mtok"]
    standard_cost = in_cost + out_cost
    stats.cost_standard_usd = round(standard_cost, 6)
    stats.cost_batch_usd = round(standard_cost * (1 - pricing["batch_discount"]), 6)

    # ── Timing ──────────────────────────────────────────────────────────
    stats.end_time = time.perf_counter()
    stats.duration_seconds = round(stats.end_time - stats.start_time, 2)

    return stats
