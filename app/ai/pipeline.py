"""
AI Answer Resolver Pipeline.
Orchestrates the entire end-to-end flow:
1. Parses classic format TXT quiz.
2. Splits questions into already-resolved and unresolved.
3. Chunks unresolved questions into optimal token payloads.
4. Resolves answers using Claude API (Standard or Message Batch).
5. Merges results back into a single ordered list with confidence ratings.
6. Computes token usage, cost, and confidence statistics.
"""

from __future__ import annotations

import asyncio
import time
from typing import Callable, List, Dict, Any, Awaitable, Literal

from app.models.question import RawQuestion
from app.utils.logger import get_logger

from app.ai.txt_parser import TXTQuizParser, split_resolved_unresolved
from app.ai.docx_parser import AIRawQuestion, DOCXQuizParser
from app.ai.chunker import QuestionChunker
from app.ai.claude_client import AsyncClaudeClient
from app.ai.batch_processor import ClaudeBatchProcessor
from app.ai.poller import BatchPoller
from app.ai.confidence import ConfidenceClassifier, ConfidenceTier
from app.ai.merger import AnswerMerger, MergeResult, ResolvedQuestion
from app.ai.statistics import AIStatistics, compute_statistics
from app.ai.validator import AIAnswer

log = get_logger(__name__)


class AIResolverPipeline:
    """
    Orchestration pipeline for AI-powered quiz answer resolution.
    Supports both real-time concurrent Standard API requests and Message Batch API.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "claude-opus-4-8",
        use_batch: bool = False,
        chunk_size: int = 25,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.use_batch = use_batch
        self.chunk_size = chunk_size

    async def run(
        self,
        content: bytes,
        file_type: Literal["txt", "docx"] = "txt",
        progress_callback: Callable[[str, float], None] | Callable[[str, float], Awaitable[None]] | None = None,
    ) -> tuple[MergeResult, AIStatistics]:
        """
        Parse a raw TXT/DOCX file and execute the resolution pipeline.

        Parameters
        ----------
        content : Raw file content as bytes (TXT or DOCX)
        file_type : "txt" for classic text format, "docx" for Word document
        progress_callback : Callback function to report status and fractional progress (0.0 to 1.0)
        """
        async def report_progress(msg: str, frac: float) -> None:
            if progress_callback:
                if asyncio.iscoroutinefunction(progress_callback):
                    await progress_callback(msg, frac)
                else:
                    progress_callback(msg, frac)

        # ── 1. Parse ────────────────────────────────────────────────────────
        await report_progress("Fayl tahlil qilinmoqda…", 0.05)

        if file_type == "docx":
            raw_ai_qs = DOCXQuizParser().parse(content)
        else:
            raw_ai_qs = [
                AIRawQuestion(question=q, image=None)
                for q in TXTQuizParser().parse(content.decode("utf-8"))
            ]

        if not raw_ai_qs:
            raise ValueError("Faylda hech qanday savol topilmadi.")

        return await self.resolve_raw_questions(raw_ai_qs, progress_callback)

    async def resolve_raw_questions(
        self,
        raw_ai_qs: List[AIRawQuestion],
        progress_callback: Callable[[str, float], None] | Callable[[str, float], Awaitable[None]] | None = None,
    ) -> tuple[MergeResult, AIStatistics]:
        """
        Resolve a list of already-parsed AIRawQuestion objects, skipping the
        file-parsing step. Used when the caller already has parsed questions
        (with real image bytes attached) from another source — e.g. the
        bot's main Parser pipeline — and wants to feed them straight into AI
        resolving without a lossy round-trip through the TXT/DOCX format.
        """
        start_time = time.perf_counter()
        warnings: List[str] = []

        async def report_progress(msg: str, frac: float) -> None:
            if progress_callback:
                if asyncio.iscoroutinefunction(progress_callback):
                    await progress_callback(msg, frac)
                else:
                    progress_callback(msg, frac)

        all_questions = [aq.question for aq in raw_ai_qs]

        if not all_questions:
            raise ValueError("Faylda hech qanday savol topilmadi.")

        # ── 2. Split resolved / unresolved + build image map ───────────────
        await report_progress("Tayyor va yechilmagan savollar ajratilmoqda…", 0.10)
        resolved_qs, unresolved_qs = split_resolved_unresolved(all_questions)

        question_images: Dict[int, bytes] = {
            i: aq.image
            for i, aq in enumerate(raw_ai_qs)
            if aq.image is not None
        }

        log.info(
            f"Tahlil: jami={len(all_questions)}, "
            f"yechilgan={len(resolved_qs)}, yechilmagan={len(unresolved_qs)}, "
            f"rasmli={len(question_images)}"
        )

        if not unresolved_qs:
            # All questions are already resolved, direct merge bypass
            await report_progress("Barcha savollar yechilgan, AI ga yuborish shart emas.", 1.0)
            merger = AnswerMerger()
            merge_result = merger.merge(
                all_questions=all_questions,
                resolved_questions=resolved_qs,
                unresolved_questions=unresolved_qs,
                ai_answers=[],
                question_images=question_images,
            )
            stats = compute_statistics(
                questions=merge_result.questions,
                already_resolved=len(resolved_qs),
                ai_resolved=0,
                failed=0,
                chunk_count=0,
                chunk_size=self.chunk_size,
                model=self.model,
                used_batch_api=self.use_batch,
                start_time=start_time,
                input_tokens=0,
                output_tokens=0,
                warnings=merge_result.merge_warnings,
            )
            return merge_result, stats

        # ── 3. Chunk unresolved questions ──────────────────────────────────
        await report_progress("Savollar optimal bo'laklarga ajratilmoqda…", 0.15)

        resolved_id_set = {id(q) for q in resolved_qs}
        unresolved_ai_qs = [aq for aq in raw_ai_qs if id(aq.question) not in resolved_id_set]

        has_images = any(aq.image for aq in unresolved_ai_qs)
        effective_chunk_size = 8 if has_images else self.chunk_size
        chunker = QuestionChunker(chunk_size=effective_chunk_size)
        chunks = chunker.chunk_ai_questions(unresolved_ai_qs)
        chunk_count = len(chunks)

        log.info(f"Yechilmagan savollar {chunk_count} ta bo'lakka bo'lindi (chunk_size={effective_chunk_size}).")

        ai_answers: List[AIAnswer] = []

        # ── 4. Resolve via Claude API ───────────────────────────────────────
        if self.use_batch:
            # ── 4a. Message Batch API Mode ──────────────────────────────────
            await report_progress("Batch API topshiriq yaratilmoqda…", 0.20)
            batch_proc = ClaudeBatchProcessor(api_key=self.api_key, model=self.model)
            job = await batch_proc.create_batch_job(chunks)
            batch_id = job["batch_id"]

            await report_progress(f"Batch API navbatiga qo'shildi (ID: {batch_id}). Polling kutilmoqda…", 0.25)
            
            # Create a wrapper poller that scales progress from 0.25 to 0.90
            async def batch_progress_wrapper(msg: str, frac: float) -> None:
                scaled_frac = 0.25 + (frac * 0.65)
                await report_progress(msg, scaled_frac)

            poller = BatchPoller(api_key=self.api_key)
            ai_answers, batch_warnings, actual_input_tokens, actual_output_tokens = await poller.poll_until_complete(
                batch_id=batch_id,
                interval_seconds=10,
                progress_callback=batch_progress_wrapper,
            )
            warnings.extend(batch_warnings)

        else:
            # ── 4b. Standard API (Concurrent Requests) Mode ─────────────────
            await report_progress("Standard API so'rovlari boshlanmoqda…", 0.20)
            client = AsyncClaudeClient(api_key=self.api_key, model=self.model)

            completed_chunks = 0
            actual_input_tokens = 0
            actual_output_tokens = 0
            semaphore = asyncio.Semaphore(3)  # Maximum 3 concurrent requests to avoid rate limits

            async def process_chunk_with_sem(chunk: List[Dict[str, Any]], chunk_idx: int) -> tuple[List[AIAnswer], int, int]:
                nonlocal completed_chunks
                async with semaphore:
                    try:
                        res, in_tok, out_tok = await client.resolve_chunk(chunk)
                        completed_chunks += 1
                        fraction = 0.20 + (completed_chunks / chunk_count) * 0.70
                        await report_progress(
                            f"Claude so'rovlari: {completed_chunks}/{chunk_count} chunk bajarildi",
                            fraction
                        )
                        return res, in_tok, out_tok
                    except Exception as e:
                        log.error(f"Chunk-{chunk_idx} yechishda xatolik: {e}")
                        # Return empty lists or placeholders to continue gracefully
                        warnings.append(f"{chunk_idx}-blokni yechishda xatolik yuz berdi: {e}")
                        return [], 0, 0

            tasks = [process_chunk_with_sem(chunk, idx) for idx, chunk in enumerate(chunks, start=1)]
            results = await asyncio.gather(*tasks)
            for res_list, in_tok, out_tok in results:
                ai_answers.extend(res_list)
                actual_input_tokens += in_tok
                actual_output_tokens += out_tok

        # ── 5. Merge answers ────────────────────────────────────────────────
        await report_progress("Natijalar asl ro'yxatga birlashtirilmoqda…", 0.92)
        merger = AnswerMerger()
        merge_result = merger.merge(
            all_questions=all_questions,
            resolved_questions=resolved_qs,
            unresolved_questions=unresolved_qs,
            ai_answers=ai_answers,
            question_images=question_images,
        )

        # Append any execution pipeline warnings
        merge_result.merge_warnings.extend(warnings)

        # ── 6. Compute statistics ───────────────────────────────────────────
        await report_progress("Statistika va sarf-xarajatlar hisoblanmoqda…", 0.98)
        stats = compute_statistics(
            questions=merge_result.questions,
            already_resolved=merge_result.already_resolved,
            ai_resolved=merge_result.ai_resolved,
            failed=merge_result.failed,
            chunk_count=chunk_count,
            chunk_size=self.chunk_size,
            model=self.model,
            used_batch_api=self.use_batch,
            start_time=start_time,
            input_tokens=actual_input_tokens,
            output_tokens=actual_output_tokens,
            warnings=merge_result.merge_warnings,
        )

        await report_progress("Jarayon muvaffaqiyatli yakunlandi!", 1.0)
        return merge_result, stats

    async def retry_non_trusted(
        self,
        merge_result: MergeResult,
        min_confidence: float = 0.90,
        progress_callback: Callable[[str, float], None] | Callable[[str, float], Awaitable[None]] | None = None,
    ) -> tuple[MergeResult, AIStatistics]:
        """
        Re-send questions below *min_confidence* to Claude and update the merge result.
        Always uses Standard API (not batch) for fast turnaround.
        """
        start_time = time.perf_counter()
        warnings: List[str] = []

        async def report_progress(msg: str, frac: float) -> None:
            if progress_callback:
                if asyncio.iscoroutinefunction(progress_callback):
                    await progress_callback(msg, frac)
                else:
                    progress_callback(msg, frac)

        non_trusted: List[tuple[int, ResolvedQuestion]] = [
            (idx, q) for idx, q in enumerate(merge_result.questions)
            if q.cf < min_confidence
        ]

        if not non_trusted:
            await report_progress(
                f"Barcha savollar {min_confidence:.0%} dan yuqori — qayta yuborish shart emas.", 1.0
            )
            stats = compute_statistics(
                questions=merge_result.questions,
                already_resolved=merge_result.already_resolved,
                ai_resolved=merge_result.ai_resolved,
                failed=merge_result.failed,
                chunk_count=0, chunk_size=self.chunk_size,
                model=self.model, used_batch_api=False,
                start_time=start_time, input_tokens=0, output_tokens=0, warnings=[],
            )
            return merge_result, stats

        await report_progress(
            f"{len(non_trusted)} ta ishonchsiz savol qayta yuborilmoqda…", 0.10
        )

        chunk_items: List[Dict[str, Any]] = []
        for seq, (_orig_idx, q) in enumerate(non_trusted, start=1):
            chunk_items.append({"id": seq, "q": q.q, "o": list(q.o)})

        chunks: List[List[Dict[str, Any]]] = []
        current: List[Dict[str, Any]] = []
        for item in chunk_items:
            current.append(item)
            if len(current) >= self.chunk_size:
                chunks.append(current)
                current = []
        if current:
            chunks.append(current)

        chunk_count = len(chunks)
        client = AsyncClaudeClient(api_key=self.api_key, model=self.model)
        ai_answers: List[AIAnswer] = []

        completed_chunks = 0
        actual_input_tokens = 0
        actual_output_tokens = 0
        semaphore = asyncio.Semaphore(3)

        async def process_chunk_with_sem(chunk: List[Dict[str, Any]], chunk_idx: int) -> tuple[List[AIAnswer], int, int]:
            nonlocal completed_chunks
            async with semaphore:
                try:
                    res, in_tok, out_tok = await client.resolve_chunk(chunk)
                    completed_chunks += 1
                    fraction = 0.15 + (completed_chunks / chunk_count) * 0.70
                    await report_progress(
                        f"Qayta yechish: {completed_chunks}/{chunk_count} chunk bajarildi",
                        fraction,
                    )
                    return res, in_tok, out_tok
                except Exception as e:
                    log.error(f"Retry chunk-{chunk_idx} xatoligi: {e}")
                    warnings.append(f"Qayta yechish: {chunk_idx}-blokda xatolik: {e}")
                    return [], 0, 0

        tasks = [process_chunk_with_sem(c, i) for i, c in enumerate(chunks, start=1)]
        results = await asyncio.gather(*tasks)
        for res_list, in_tok, out_tok in results:
            ai_answers.extend(res_list)
            actual_input_tokens += in_tok
            actual_output_tokens += out_tok

        await report_progress("Natijalar yangilanmoqda…", 0.90)

        ai_map: Dict[int, AIAnswer] = {a.id: a for a in ai_answers}
        retry_resolved = 0
        retry_failed = 0

        for seq, (orig_idx, old_q) in enumerate(non_trusted, start=1):
            ai_answer = ai_map.get(seq)
            if ai_answer and ai_answer.c != -1 and 0 <= ai_answer.c < len(old_q.o):
                tier = ConfidenceClassifier.classify(ai_answer.cf)
                merge_result.questions[orig_idx] = ResolvedQuestion(
                    q=old_q.q, o=list(old_q.o), c=ai_answer.c,
                    cf=ai_answer.cf, source="ai", tier=tier.value,
                )
                retry_resolved += 1
            else:
                retry_failed += 1

        merge_result.ai_resolved = sum(
            1 for q in merge_result.questions if q.source == "ai" and q.c != -1
        )
        merge_result.failed = sum(
            1 for q in merge_result.questions if q.source == "ai" and q.c == -1
        )

        await report_progress("Statistika hisoblanmoqda…", 0.98)
        stats = compute_statistics(
            questions=merge_result.questions,
            already_resolved=merge_result.already_resolved,
            ai_resolved=merge_result.ai_resolved,
            failed=merge_result.failed,
            chunk_count=chunk_count, chunk_size=self.chunk_size,
            model=self.model, used_batch_api=False,
            start_time=start_time,
            input_tokens=actual_input_tokens,
            output_tokens=actual_output_tokens,
            warnings=merge_result.merge_warnings + warnings,
        )

        log.info(
            f"Retry yakunlandi: qayta yuborilgan={len(non_trusted)}, "
            f"yechildi={retry_resolved}, muvaffaqiyatsiz={retry_failed}"
        )
        await report_progress("Qayta yechish muvaffaqiyatli yakunlandi!", 1.0)
        return merge_result, stats
