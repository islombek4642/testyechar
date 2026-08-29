"""
Question validation engine.

Converts raw parsed questions into validated :class:`ParsedQuestion`
objects, collecting warnings and errors for every question that
does not meet quality criteria.
"""

from __future__ import annotations

from typing import List

from app.config import settings
from app.models.question import (
    ParsedQuestion,
    RawQuestion,
    ValidationResult,
)
from app.utils.logger import get_logger

log = get_logger(__name__)


class QuestionValidator:
    """
    Validate a list of :class:`RawQuestion` objects.

    Usage::

        validator = QuestionValidator()
        results = validator.validate_all(raw_questions)
        valid = [r.question for r in results if r.is_valid]
    """

    def __init__(self) -> None:
        self.duplicate_count: int = 0
        self.removed_duplicate_texts: list[str] = []

    def validate_all(
        self, raw_questions: List[RawQuestion]
    ) -> List[ValidationResult]:
        """
        Validate every raw question and return results, deduplicating by question text.

        Deduplication strategy (two-pass):
          Pass 1 — validate all questions and determine the best result per unique
                   question text (valid result preferred over invalid).
          Pass 2 — emit results in original order: first occurrence of each text
                   gets the best result; subsequent occurrences are skipped.

        This ensures that if a question appears twice — once without options (invalid)
        and once with complete options (valid) — the valid version is kept.
        """
        # ── Pass 1: validate all, collect best result per question key ──
        keyed: list[tuple[str, ValidationResult]] = []
        best: dict[str, ValidationResult] = {}

        for idx, raw in enumerate(raw_questions, start=1):
            result = self._validate_one(raw, idx)
            q_key = raw.question_text.strip().lower()
            # Always include options in the dedup key so questions sharing
            # the same stem but with different answer choices are kept
            # (e.g. image-based tests where every question reads "choose
            # the matching word" but each has a unique correct answer as
            # the first option, making each question visually distinct).
            # Use ordered (not sorted) options so questions that share the
            # same option *set* but in a different order are not collapsed.
            options_sig = "|".join(o.text.strip().lower() for o in raw.options)
            q_key = q_key + "::" + options_sig
            keyed.append((q_key, result))

            if not q_key:
                continue
            if q_key not in best:
                best[q_key] = result
            elif result.is_valid and not best[q_key].is_valid:
                best[q_key] = result  # upgrade: valid beats invalid

        # ── Pass 2: emit in original order, one result per unique key ──
        seen: set[str] = set()
        results: list[ValidationResult] = []
        duplicate_count = 0
        self.duplicate_count = 0
        self.removed_duplicate_texts = []

        for q_key, result in keyed:
            if not q_key:
                results.append(result)
                continue
            if q_key in seen:
                duplicate_count += 1
                display = (result.question.q if result.question else q_key)[:80]
                log.info(f"Takroriy savol olib tashlandi: «{display}»")
                self.removed_duplicate_texts.append(display)
                continue
            seen.add(q_key)
            results.append(best[q_key])  # emit best (valid-preferred) version

        self.duplicate_count = duplicate_count
        valid_count = sum(1 for r in results if r.is_valid)
        invalid_count = len(results) - valid_count
        warning_count = sum(len(r.warnings) for r in results)

        log.info(
            f"Validation complete — "
            f"[green]{valid_count}[/] valid, "
            f"[red]{invalid_count}[/] invalid, "
            f"[yellow]{warning_count}[/] warnings"
            + (f", [yellow]{duplicate_count}[/] takroriy savol olib tashlandi" if duplicate_count else "")
        )

        return results

    # ── Internal ────────────────────────────────────────────────────────

    def _validate_one(self, raw: RawQuestion, idx: int) -> ValidationResult:
        """Validate a single raw question."""
        warnings: List[str] = list(raw.warnings)
        errors: List[str] = []
        prefix = f"Savol #{idx} (satr {raw.line_start})"

        # ── Check question text ─────────────────────────────────────────
        q_text = raw.question_text.strip()
        if not q_text:
            errors.append(f"{prefix}: Savol matni bo'sh.")
        elif len(q_text) < settings.min_question_length:
            warnings.append(
                f"{prefix}: Savol matni juda qisqa ({len(q_text)} belgi)."
            )

        # ── Check options ───────────────────────────────────────────────
        # Keep each option's text paired with its own RawOption throughout —
        # filtering the text list and zipping it against the unfiltered
        # raw.options list (as this used to do) misaligns text with
        # is_correct as soon as any option but the last is empty, silently
        # attributing the correct-answer flag to the wrong option.
        non_empty_pairs = [(o.text.strip(), o) for o in raw.options if o.text.strip()]
        empty_count = len(raw.options) - len(non_empty_pairs)

        if len(non_empty_pairs) < settings.min_options:
            errors.append(
                f"{prefix}: Kamida {settings.min_options} ta variant kerak "
                f"(topildi: {len(non_empty_pairs)})."
            )
        elif len(non_empty_pairs) > settings.max_options:
            warnings.append(
                f"{prefix}: {len(non_empty_pairs)} ta variant topildi "
                f"(max {settings.max_options}). Ortiqchalari olib tashlanadi."
            )
            non_empty_pairs = non_empty_pairs[: settings.max_options]

        if empty_count > 0:
            warnings.append(
                f"{prefix}: {empty_count} ta bo'sh variant olib tashlandi."
            )

        # ── Check correct answer count ──────────────────────────────────
        correct_count = raw.correct_count
        if correct_count == 0:
            warnings.append(f"{prefix}: To'g'ri javob belgilanmagan.")
        elif correct_count > 1:
            warnings.append(
                f"{prefix}: {correct_count} ta to'g'ri javob belgilangan. "
                f"Faqat birinchisi qabul qilinadi."
            )

        # ── Check for duplicate options ─────────────────────────────────
        seen: dict[str, int] = {}
        unique_options: list[str] = []
        unique_correct: list[bool] = []
        for opt, raw_opt in non_empty_pairs:
            if opt in seen:
                warnings.append(
                    f"{prefix}: Takroriy variant olib tashlandi: «{opt}»"
                )
                # A later duplicate marked correct (e.g. by bold-text
                # detection) must not lose that status just because an
                # earlier, unmarked duplicate happened to be kept instead.
                if raw_opt.is_correct:
                    unique_correct[seen[opt]] = True
                continue
            seen[opt] = len(unique_options)
            unique_options.append(opt)
            unique_correct.append(raw_opt.is_correct)

        # ── Flag questions that don't end up with exactly 4 options ──────
        # Not an error (some legitimate question sets use 3, 5, or 6
        # options), but this test bank format is expected to be strictly
        # 4-way multiple choice, so a different count is worth a human
        # double-checking — often a sign of a parsing/merge glitch.
        if unique_options and len(unique_options) != 4:
            warnings.append(
                f"{prefix}: 4 emas, {len(unique_options)} ta variant aniqlandi. "
                f"Qo'lda tekshirib chiqing."
            )

        # ── Build validated question if no errors ───────────────────────
        if errors:
            for e in errors:
                log.warning(e)
            return ValidationResult(
                is_valid=False,
                errors=errors,
                warnings=warnings,
                source_line=raw.line_start,
                raw_images=raw.images,
            )

        # Find the correct answer index (first one wins, -1 if none)
        correct_index = -1
        for i, is_c in enumerate(unique_correct):
            if is_c:
                correct_index = i
                break

        try:
            question = ParsedQuestion(
                q=q_text,
                o=unique_options,
                c=correct_index,
                img=raw.images,
            )
        except ValueError as exc:
            errors.append(f"{prefix}: Validatsiya xatosi — {exc}")
            return ValidationResult(
                is_valid=False,
                errors=errors,
                warnings=warnings,
                source_line=raw.line_start,
                raw_images=raw.images,
            )

        for w in warnings:
            log.info(w)

        return ValidationResult(
            question=question,
            is_valid=True,
            warnings=warnings,
            source_line=raw.line_start,
            raw_images=raw.images,
        )
