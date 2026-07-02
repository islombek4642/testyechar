"""
Main processing pipeline.

Orchestrates the full flow:  extract → clean → parse → validate → export.

Each stage is independently testable and replaceable.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

from app.cleaner import TextCleaner
from app.config import settings
from app.exporter import JSONExporter
from app.extractor import PDFExtractor
from app.models.question import ParsedQuestion, ParsingStats, ValidationResult
from app.parser import QuestionParser, FormatType
from app.utils.logger import get_logger
from app.validator import QuestionValidator

log = get_logger(__name__)


@dataclass
class PipelineResult:
    """Aggregated output of a full pipeline run."""

    questions: List[ParsedQuestion] = field(default_factory=list)
    validation_results: List[ValidationResult] = field(default_factory=list)
    stats: ParsingStats = field(default_factory=ParsingStats)
    json_string: str = ""
    output_path: Optional[Path] = None
    raw_text: str = ""
    cleaned_text: str = ""
    detected_format: Optional[str] = None
    removed_duplicates: List[str] = field(default_factory=list)


class ParsingPipeline:
    """
    End-to-end pipeline that processes a PDF file into validated JSON.

    Usage::

        pipeline = ParsingPipeline()
        result = pipeline.run(Path("test.pdf"))
        print(result.json_string)

    Pass an optional ``progress_callback`` to receive stage updates
    (used by the Streamlit UI for progress bars).
    """

    def __init__(self) -> None:
        self.extractor = PDFExtractor()
        self.cleaner = TextCleaner()
        self.parser = QuestionParser()
        self.validator = QuestionValidator()
        self.exporter = JSONExporter()

    def run(
        self,
        pdf_path: Path,
        format_type: FormatType = FormatType.AUTO,
        progress_callback: Callable[[str, float], None] | None = None,
    ) -> PipelineResult:
        """
        Execute the full pipeline on *pdf_path*.

        Args:
            pdf_path: Path to the PDF file.
            progress_callback: Optional ``(stage_name, fraction)`` callback.

        Returns:
            PipelineResult with all outputs and statistics.
        """
        result = PipelineResult()
        start = time.perf_counter()

        def _progress(stage: str, frac: float) -> None:
            if progress_callback:
                progress_callback(stage, frac)

        try:
            # ── Stage 1: Extract ────────────────────────────────────────
            ext = pdf_path.suffix.lower()
            if ext == ".docx":
                from app.extractor.docx_extractor import DOCXExtractor
                extractor = DOCXExtractor()
                _progress("DOCX hujjatidan matn ajratilmoqda…", 0.1)
            elif ext == ".doc":
                from app.extractor.doc_extractor import DOCExtractor
                extractor = DOCExtractor()
                _progress("DOC hujjatidan matn ajratilmoqda…", 0.1)
            elif ext == ".xlsx":
                from app.extractor.xlsx_extractor import XLSXExtractor
                extractor = XLSXExtractor()
                _progress("Excel hujjatidan matn ajratilmoqda…", 0.1)
            elif ext == ".txt":
                from app.extractor.txt_extractor import TXTExtractor
                extractor = TXTExtractor()
                _progress("TXT faylidan matn ajratilmoqda…", 0.1)
            else:
                extractor = self.extractor
                _progress("PDF faylidan matn ajratilmoqda…", 0.1)

            log.info("[bold]═══ Stage 1: Extraction ═══[/]")
            extraction = extractor.extract(pdf_path)

            if extraction.is_empty:
                log.error("PDF bo'sh yoki matn topilmadi.")
                result.stats = ParsingStats(
                    filename=pdf_path.name,
                    pages_processed=extraction.page_count,
                    duration_seconds=time.perf_counter() - start,
                )
                return result

            result.raw_text = extraction.full_text

            # ── Stage 1.5: Pre-clean marker injection ───────────────────
            # Detect "? questions, no = option markers" format and add = markers
            # BEFORE the text cleaner runs — otherwise fix_broken_line_joins
            # merges adjacent option lines that both start/end with lowercase.
            pre_clean_text = extraction.full_text
            if format_type == FormatType.AUTO:
                _temp_parser = QuestionParser()
                _converted = _temp_parser._preprocess_no_option_markers(pre_clean_text)
                if _converted is not None:
                    pre_clean_text = _converted

            # ── Stage 2: Clean ──────────────────────────────────────────
            _progress("Matn tozalanmoqda…", 0.3)
            log.info("[bold]═══ Stage 2: Cleaning ═══[/]")
            result.cleaned_text = self.cleaner.clean(pre_clean_text)

            # ── Stage 3: Parse ──────────────────────────────────────────
            _progress("Savollar tahlil qilinmoqda…", 0.5)
            log.info("[bold]═══ Stage 3: Parsing ═══[/]")
            self.parser = QuestionParser(format_type=format_type)
            raw_questions = self.parser.parse(result.cleaned_text)
            result.detected_format = (
                self.parser.detected_format.value
                if self.parser.detected_format
                else format_type.value
            )

            # ── Stage 4: Validate ───────────────────────────────────────
            _progress("Savollar tekshirilmoqda…", 0.7)
            log.info("[bold]═══ Stage 4: Validation ═══[/]")
            result.validation_results = self.validator.validate_all(
                raw_questions
            )
            result.questions = [
                vr.question
                for vr in result.validation_results
                if vr.is_valid and vr.question is not None
            ]
            result.removed_duplicates = self.validator.removed_duplicate_texts

            # ── Stage 5: Export ─────────────────────────────────────────
            _progress("JSON eksport qilinmoqda…", 0.9)
            log.info("[bold]═══ Stage 5: Export ═══[/]")
            result.json_string = self.exporter.to_json_string(
                result.questions
            )
            result.output_path = self.exporter.to_file(result.questions)

            # ── Statistics ──────────────────────────────────────────────
            elapsed = time.perf_counter() - start
            result.stats = ParsingStats(
                total_raw=len(raw_questions),
                total_valid=len(result.questions),
                total_invalid=sum(
                    1 for vr in result.validation_results if not vr.is_valid
                ),
                total_warnings=sum(
                    len(vr.warnings) for vr in result.validation_results
                ),
                total_duplicates=self.validator.duplicate_count,
                pages_processed=extraction.page_count,
                characters_processed=extraction.character_count,
                duration_seconds=round(elapsed, 3),
                filename=pdf_path.name,
            )

            _progress("Tayyor!", 1.0)
            log.info(
                f"[bold green]Pipeline complete[/] — "
                f"{result.stats.total_valid}/{result.stats.total_raw} "
                f"questions valid in {result.stats.duration_seconds}s"
            )

        except Exception as exc:
            elapsed = time.perf_counter() - start
            log.error(f"Pipeline failed: {exc}", exc_info=True)
            result.stats = ParsingStats(
                filename=pdf_path.name,
                duration_seconds=round(elapsed, 3),
            )

        return result
