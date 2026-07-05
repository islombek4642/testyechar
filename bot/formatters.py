"""Summary-message builders (HTML parse mode, Uzbek strings).

Kept deliberately minimal: filename, question count, answered/unanswered
split, image count (if any), and duration. No model name, tokens, cost,
or confidence-tier detail — end users aren't meant to know AI is involved
at all, only that a result is ready.
"""
from __future__ import annotations

import html

from app.ai.merger import MergeResult
from app.ai.statistics import AIStatistics
from app.core.pipeline import PipelineResult


def format_parser_summary(filename: str, result: PipelineResult) -> str:
    questions = result.questions
    answered = sum(1 for q in questions if q.c != -1)
    unanswered = len(questions) - answered
    image_count = sum(1 for q in questions if q.img)

    lines = [
        "📝 <b>Tahlil yakunlandi</b>",
        f"📁 Fayl: <code>{html.escape(filename)}</code>",
        f"❓ Jami savollar: <b>{len(questions)}</b>",
        f"✔️ Javobli: <b>{answered}</b>  |  ❌ Javobsiz: <b>{unanswered}</b>",
    ]
    if image_count:
        lines.append(f"🖼 Rasmli savollar: <b>{image_count}</b>")
    if result.removed_duplicates:
        lines.append(f"♻️ Dublikatlar (olib tashlandi): <b>{len(result.removed_duplicates)}</b>")
    lines.append(f"⏱ Davomiylik: <b>{result.stats.duration_seconds:.1f} soniya</b>")
    return "\n".join(lines)


def format_resolver_summary(filename: str, merge: MergeResult, stats: AIStatistics) -> str:
    lines = [
        "✅ <b>Javoblar aniqlandi</b>",
        f"📁 Fayl: <code>{html.escape(filename)}</code>",
        f"❓ Jami savollar: <b>{stats.total_questions}</b>",
        f"✔️ Javobli: <b>{stats.total_questions - stats.failed}</b>  |  ❌ Javobsiz: <b>{stats.failed}</b>",
    ]
    if merge.images:
        lines.append(f"🖼 Rasmli savollar: <b>{len(merge.images)}</b>")
    lines.append(f"⏱ Davomiylik: <b>{stats.duration_seconds:.0f} soniya</b>")
    return "\n".join(lines)
