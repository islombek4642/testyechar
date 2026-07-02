"""
app/ai — AI Answer Resolver package.
"""

from .txt_parser import TXTQuizParser, split_resolved_unresolved
from .chunker import QuestionChunker
from .claude_client import AsyncClaudeClient
from .batch_processor import ClaudeBatchProcessor
from .poller import BatchPoller
from .merger import AnswerMerger, ResolvedQuestion, MergeResult
from .confidence import ConfidenceClassifier, ConfidenceTier
from .validator import AIAnswer, AIAnswerList, AIValidationReport
from .statistics import AIStatistics, compute_statistics
from .exporter import AIExporter
from .pipeline import AIResolverPipeline

__all__ = [
    "TXTQuizParser",
    "split_resolved_unresolved",
    "QuestionChunker",
    "AsyncClaudeClient",
    "ClaudeBatchProcessor",
    "BatchPoller",
    "AnswerMerger",
    "ResolvedQuestion",
    "MergeResult",
    "ConfidenceClassifier",
    "ConfidenceTier",
    "AIAnswer",
    "AIAnswerList",
    "AIValidationReport",
    "AIStatistics",
    "compute_statistics",
    "AIExporter",
    "AIResolverPipeline",
]
