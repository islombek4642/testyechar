"""
Batch Processor for Claude Message Batch API.
Allows processing large volumes of questions (500+) with a 50% discount and higher rate limits.
"""

from __future__ import annotations

import asyncio
import json
from typing import Dict, Any, List

import httpx
from anthropic import AsyncAnthropic, APIConnectionError, APITimeoutError
from app.ai.prompts import CLAUDE_SYSTEM_PROMPT, WEB_SEARCH_TOOL, make_user_prompt, make_multimodal_content
from app.utils.logger import get_logger

log = get_logger(__name__)


class ClaudeBatchProcessor:
    """
    Manages Message Batch API jobs with Claude.
    """

    def __init__(self, api_key: str, model: str = "claude-opus-4-8") -> None:
        self.api_key = api_key
        self.model = model
        self.client = AsyncAnthropic(
            api_key=api_key,
            timeout=httpx.Timeout(120.0, connect=30.0),
            max_retries=4,
        )

    async def create_batch_job(self, chunks: List[List[Dict[str, Any]]]) -> Dict[str, Any]:
        """
        Create a Message Batch API job for the given chunks of questions.
        """
        log.info(f"Batch so'rovi tayyorlanmoqda. Jami chunklar soni: {len(chunks)}")
        
        requests = []
        for chunk_idx, chunk in enumerate(chunks, start=1):
            has_images = any(q.get("img") for q in chunk)
            if has_images:
                user_content = make_multimodal_content(chunk)
            else:
                chunk_json = json.dumps({"questions": chunk}, ensure_ascii=False)
                user_content = make_user_prompt(chunk_json)

            params = {
                "model": self.model,
                "max_tokens": 4000,
                "system": CLAUDE_SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": user_content}],
                "tools": [WEB_SEARCH_TOOL],
            }
            if "claude-3" in self.model.lower():
                params["temperature"] = 0.0
            else:
                # Fikrlash (thinking) o'chiriladi: bu vazifa oddiy JSON qaytarish,
                # fikrlashdan foyda yo'q, lekin ba'zi modellar (masalan Sonnet 5)
                # uni standart yoqib qo'yadi va u max_tokens byudjetini
                # (shu bilan haqiqiy javobni kesib qo'yishi mumkin) yeb qo'yadi.
                params["thinking"] = {"type": "disabled"}

            requests.append({
                "custom_id": f"chunk-{chunk_idx}",
                "params": params
            })

        log.info("Claude Batch API job yaratilmoqda...")
        
        # Retry batch creation in case of connection drop
        max_retries = 3
        delay = 5.0
        for attempt in range(1, max_retries + 1):
            try:
                batch = await self.client.beta.messages.batches.create(
                    requests=requests
                )
                break
            except (APIConnectionError, APITimeoutError) as e:
                if attempt == max_retries:
                    raise
                log.warning(
                    f"Batch job yaratishda ulanish xatoligi (urinish {attempt}/{max_retries}): {e}. "
                    f"{delay} soniyadan so'ng qayta uriniladi..."
                )
                await asyncio.sleep(delay)
                delay *= 2

        log.info(f"Batch API job muvaffaqiyatli yaratildi. ID: {batch.id}")
        return {
            "batch_id": batch.id,
            "status": batch.processing_status,
            "total_requests": len(requests),
            "processing_count": batch.request_counts.processing,
            "succeeded_count": batch.request_counts.succeeded,
            "errored_count": batch.request_counts.errored,
        }

    async def retrieve_batch_status(self, batch_id: str) -> Dict[str, Any]:
        """
        Retrieve the latest status of an active batch job.
        """
        batch = await self.client.beta.messages.batches.retrieve(batch_id)
        return {
            "batch_id": batch.id,
            "status": batch.processing_status,
            "processing_count": batch.request_counts.processing,
            "succeeded_count": batch.request_counts.succeeded,
            "errored_count": batch.request_counts.errored,
            "canceled_count": batch.request_counts.canceled,
            "expired_count": batch.request_counts.expired,
        }

    async def cancel_batch_job(self, batch_id: str) -> Dict[str, Any]:
        """
        Cancel a running batch job.
        """
        batch = await self.client.beta.messages.batches.cancel(batch_id)
        return {
            "batch_id": batch.id,
            "status": batch.processing_status,
        }
