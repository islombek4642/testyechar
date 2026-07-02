"""Summary-message builders (HTML parse mode, Uzbek strings)."""
from __future__ import annotations

import html
from typing import List, Optional

from app.ai.merger import MergeResult
from app.ai.statistics import AIStatistics
from app.core.pipeline import PipelineResult

CHOOSE_FORMAT = "\n⬇️ Yuklab olish formatini tanlang:"


def format_parser_summary(
    filename: str,
    result: PipelineResult,
    extra_warnings: Optional[List[str]] = None,
) -> str:
    s = result.stats
    lines = [
        "📝 <b>Tahlil yakunlandi</b>",
        f"📁 Fayl: <code>{html.escape(filename)}</code>",
        f"🧩 Aniqlangan format: <b>{html.escape(str(result.detected_format or 'NOMA’LUM'))}</b>",
        f"❓ Topilgan savollar: <b>{s.total_raw}</b>",
        f"✅ Yaroqli: <b>{s.total_valid}</b>  |  ❌ Yaroqsiz: <b>{s.total_invalid}</b>",
    ]
    if s.total_duplicates:
        lines.append(f"♻️ Olib tashlangan dublikatlar: <b>{s.total_duplicates}</b>")
    if s.total_warnings:
        lines.append(f"⚠️ Ogohlantirishlar soni: <b>{s.total_warnings}</b>")
    lines.append(f"⏱ Davomiylik: <b>{s.duration_seconds:.1f} soniya</b>")
    for w in extra_warnings or []:
        lines.append(f"⚠️ {html.escape(w)}")
    lines.append(CHOOSE_FORMAT)
    return "\n".join(lines)


def format_resolver_summary(
    filename: str,
    merge: MergeResult,
    stats: AIStatistics,
) -> str:
    lines = [
        "🤖 <b>AI yechish yakunlandi</b>",
        f"📁 Fayl: <code>{html.escape(filename)}</code>",
        f"🧠 Model: <code>{html.escape(stats.model)}</code> (Batch API, ~50% chegirma)",
        f"❓ Jami savollar: <b>{stats.total_questions}</b>",
        f"✔️ Oldindan javobli: <b>{stats.already_resolved}</b>",
        f"🤖 AI yechdi: <b>{stats.ai_resolved}</b>  |  ❌ Yechilmadi: <b>{stats.failed}</b>",
        "",
        "📊 <b>Ishonch darajasi (AI javoblari):</b>",
        f"  🟢 TRUSTED: <b>{stats.trusted_count}</b>",
        f"  🟡 WARNING: <b>{stats.warning_count}</b>",
        f"  🔴 MANUAL REVIEW: <b>{stats.manual_review_count}</b>",
        f"  O'rtacha ishonch: <b>{stats.average_confidence:.2f}</b>",
        "",
        f"🪙 Tokenlar (taxminiy): <b>{stats.estimated_total_tokens:,}</b>",
        f"💵 Taxminiy narx (Batch): <b>${stats.estimated_cost_batch_usd:.4f}</b>",
        f"⏱ Davomiylik: <b>{stats.duration_seconds:.0f} soniya</b>",
        CHOOSE_FORMAT,
    ]
    return "\n".join(lines)
