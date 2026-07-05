from app.ai.merger import MergeResult, ResolvedQuestion
from app.ai.statistics import AIStatistics
from app.core.pipeline import PipelineResult
from app.models.question import ParsedQuestion, ParsingStats

from bot.formatters import format_parser_summary, format_resolver_summary


def _parser_result(questions=None, duration_seconds=4.2) -> PipelineResult:
    r = PipelineResult()
    r.questions = questions if questions is not None else [
        ParsedQuestion(q="S1?", o=["A", "B"], c=0),
        ParsedQuestion(q="S2?", o=["A", "B"], c=-1),
    ]
    r.stats = ParsingStats(duration_seconds=duration_seconds)
    return r


def test_parser_summary_shows_only_the_5_essentials():
    text = format_parser_summary("test.pdf", _parser_result())
    assert "test.pdf" in text
    assert "Jami savollar" in text and "2" in text
    assert "Javobli" in text and "Javobsiz" in text
    assert "4.2" in text
    # Nothing AI/implementation-detail related should leak into the message.
    for hidden in ("claude", "Claude", "model", "token", "narx", "TRUSTED", "format"):
        assert hidden not in text


def test_parser_summary_answered_unanswered_counts_are_correct():
    questions = [
        ParsedQuestion(q="S1?", o=["A", "B"], c=0),
        ParsedQuestion(q="S2?", o=["A", "B"], c=1),
        ParsedQuestion(q="S3?", o=["A", "B"], c=-1),
    ]
    text = format_parser_summary("t.pdf", _parser_result(questions=questions))
    assert "<b>2</b>" in text  # answered
    assert "<b>1</b>" in text  # unanswered


def test_parser_summary_shows_image_count_only_when_present():
    with_image = [ParsedQuestion(q="S1?", o=["A", "B"], c=0, img=["images/a.png"])]
    without_image = [ParsedQuestion(q="S1?", o=["A", "B"], c=0)]

    assert "Rasmli savollar" in format_parser_summary("t.pdf", _parser_result(questions=with_image))
    assert "Rasmli savollar" not in format_parser_summary("t.pdf", _parser_result(questions=without_image))


def test_resolver_summary_shows_only_the_5_essentials():
    merge = MergeResult(
        questions=[ResolvedQuestion(q="S?", o=["A"], c=0)],
        total=30, already_resolved=5, ai_resolved=23, failed=2,
    )
    stats = AIStatistics(
        total_questions=30, already_resolved=5, ai_resolved=23, failed=2,
        duration_seconds=95.0, model="claude-opus-4-8",
    )
    text = format_resolver_summary("quiz", merge, stats)
    assert "quiz" in text
    assert "Jami savollar" in text and "30" in text
    assert "Javobli" in text and "28" in text  # 30 - 2 failed
    assert "Javobsiz" in text and "2" in text
    assert "95" in text
    for hidden in ("claude-opus-4-8", "model", "token", "narx", "TRUSTED", "ishonch"):
        assert hidden not in text


def test_resolver_summary_shows_image_count_only_when_present():
    merge_with = MergeResult(questions=[], total=1, images={0: b"fake"})
    merge_without = MergeResult(questions=[], total=1)
    stats = AIStatistics(total_questions=1)

    assert "Rasmli savollar" in format_resolver_summary("q", merge_with, stats)
    assert "Rasmli savollar" not in format_resolver_summary("q", merge_without, stats)
