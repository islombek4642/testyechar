from app.ai.merger import MergeResult, ResolvedQuestion
from app.ai.statistics import AIStatistics
from app.core.pipeline import PipelineResult
from app.models.question import ParsedQuestion, ParsingStats

from bot.formatters import format_parser_summary, format_resolver_summary


def _parser_result() -> PipelineResult:
    r = PipelineResult()
    r.questions = [ParsedQuestion(q="S?", o=["A", "B"], c=0)]
    r.detected_format = "CLASSIC"
    r.stats = ParsingStats(
        total_raw=12, total_valid=10, total_invalid=2,
        total_warnings=1, total_duplicates=3, duration_seconds=4.2,
    )
    return r


def test_parser_summary_contains_key_details():
    text = format_parser_summary("test.pdf", _parser_result())
    for fragment in ("test.pdf", "CLASSIC", "12", "10", "2", "3"):
        assert fragment in text


def test_parser_summary_includes_extra_warnings():
    text = format_parser_summary("t.doc", _parser_result(), extra_warnings=["zaxira usul"])
    assert "zaxira usul" in text


def test_resolver_summary_contains_key_details():
    merge = MergeResult(
        questions=[ResolvedQuestion(q="S?", o=["A"], c=0)],
        total=30, already_resolved=5, ai_resolved=23, failed=2,
    )
    stats = AIStatistics(
        total_questions=30, already_resolved=5, ai_resolved=23, failed=2,
        trusted_count=18, warning_count=4, manual_review_count=1,
        average_confidence=0.91, estimated_total_tokens=4200,
        estimated_cost_batch_usd=0.0132, duration_seconds=95.0,
        model="claude-opus-4-8",
    )
    text = format_resolver_summary("quiz.txt", merge, stats)
    for fragment in ("quiz.txt", "claude-opus-4-8", "30", "23", "18", "4", "0.0132"):
        assert fragment in text
