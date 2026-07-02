"""
Batch Poller for Claude Batch API results.
Periodically polls batch status and downloads/decodes results.
"""

from __future__ import annotations

import asyncio
import json
from typing import Dict, Any, List, Callable, Awaitable

import httpx
from anthropic import AsyncAnthropic, APITimeoutError
from app.ai.validator import AIAnswer, AIAnswerList
from app.ai.claude_client import AsyncClaudeClient
from app.utils.logger import get_logger

log = get_logger(__name__)


class BatchPoller:
    """
    Handles polling and parsing results of Claude Message Batch jobs.
    """

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.client = AsyncAnthropic(
            api_key=api_key,
            timeout=httpx.Timeout(120.0, connect=30.0),
            max_retries=4,
        )

    async def _retrieve_with_retry(self, batch_id: str, max_retries: int = 5) -> Any:
        """Retrieve batch status with manual retry on timeout."""
        delay = 5.0
        for attempt in range(1, max_retries + 1):
            try:
                return await self.client.beta.messages.batches.retrieve(batch_id)
            except APITimeoutError:
                if attempt == max_retries:
                    raise
                log.warning(
                    f"Batch retrieve timeout (urinish {attempt}/{max_retries}). "
                    f"{delay}s dan keyin qayta uriniladi..."
                )
                await asyncio.sleep(delay)
                delay *= 2

    async def poll_until_complete(
        self,
        batch_id: str,
        interval_seconds: int = 10,
        progress_callback: Callable[[str, float], None] | Callable[[str, float], Awaitable[None]] | None = None,
    ) -> List[AIAnswer]:
        """
        Poll the active batch job until it reaches a terminal status:
        - completed
        - failed
        - expired
        - canceled
        """
        log.info(f"Batch {batch_id} kuzatish boshlandi. Polling intervali: {interval_seconds}s")
        
        # Temp client to use its clean JSON helper
        dummy_client = AsyncClaudeClient(api_key=self.api_key)

        while True:
            batch = await self._retrieve_with_retry(batch_id)
            status = batch.processing_status.lower()

            total = batch.request_counts.processing + batch.request_counts.succeeded + batch.request_counts.errored + batch.request_counts.canceled + batch.request_counts.expired
            completed_reqs = batch.request_counts.succeeded + batch.request_counts.errored + batch.request_counts.canceled + batch.request_counts.expired
            fraction = completed_reqs / total if total > 0 else 0.0

            progress_msg = (
                f"Batch statusi: {batch.processing_status.upper()} | "
                f"Bajarildi: {completed_reqs}/{total} (Muvaffaqiyatli: {batch.request_counts.succeeded}, "
                f"Xatolik: {batch.request_counts.errored})"
            )
            log.info(progress_msg)

            if progress_callback:
                if asyncio.iscoroutinefunction(progress_callback):
                    await progress_callback(progress_msg, fraction)
                else:
                    progress_callback(progress_msg, fraction)

            if status in ("completed", "ended"):
                log.info("Batch muvaffaqiyatli yakunlandi! Natijalar yuklab olinmoqda...")
                break
            elif status in ("failed", "expired", "canceled"):
                raise RuntimeError(f"Batch API kutilmaganda tugatildi. Status: {batch.processing_status.upper()}")

            await asyncio.sleep(interval_seconds)

        # Retrieve and parse JSONL results
        resolved_answers: List[AIAnswer] = []
        
        async for res in await self.client.beta.messages.batches.results(batch_id):
            # res is BetaMessageBatchIndividualResponse
            if res.result.type == "succeeded":
                # Succeeded response
                text_response = "".join(block.text for block in res.result.message.content).strip()
                cleaned_text = dummy_client._clean_json_response(text_response)

                try:
                    parsed_json = json.loads(cleaned_text)
                    answer_list = AIAnswerList.model_validate(parsed_json)
                    resolved_answers.extend(answer_list.answers)
                    log.debug(f"Chunk '{res.custom_id}' muvaffaqiyatli tahlil qilindi ({len(answer_list.answers)} ta javob).")
                except Exception as parse_err:
                    log.error(f"Chunk '{res.custom_id}' natijasini tahlil qilishda xatolik: {parse_err}")
            else:
                # Failed request in batch
                log.error(f"Batch elementi '{res.custom_id}' muvaffaqiyatsiz yakunlandi: {res.result.error}")

        return resolved_answers
