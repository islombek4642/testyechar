"""
Asynchronous Claude Client.
Handles connection pooling, rate limit retries with backoff, and JSON response parsing.
"""

from __future__ import annotations

import asyncio
import json
import random
from typing import Dict, Any, List, Optional

import httpx
from anthropic import AsyncAnthropic, APIError, RateLimitError, APIStatusError
from app.ai.prompts import CLAUDE_SYSTEM_PROMPT, make_user_prompt, make_multimodal_content
from app.ai.validator import AIAnswer, AIAnswerList
from app.utils.logger import get_logger

log = get_logger(__name__)


class AsyncClaudeClient:
    """
    Client for standard, real-time Claude API requests with exponential backoff.
    """

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6") -> None:
        self.api_key = api_key
        self.model = model
        self.client = AsyncAnthropic(
            api_key=api_key,
            timeout=httpx.Timeout(120.0, connect=30.0),
            max_retries=4,
        )

    async def resolve_chunk(
        self,
        questions: List[Dict[str, Any]],
        max_retries: int = 5,
        initial_delay: float = 2.0,
        backoff_factor: float = 2.0,
    ) -> List[AIAnswer]:
        """
        Send a chunk of questions to Claude API and parse the resolved answers.
        Implements rigorous async retries and error handling.
        """
        has_images = any(q.get("img") for q in questions)
        if has_images:
            user_content = make_multimodal_content(questions)
        else:
            questions_str = json.dumps({"questions": questions}, ensure_ascii=False)
            user_content = make_user_prompt(questions_str)

        delay = initial_delay

        for attempt in range(1, max_retries + 1):
            try:
                log.info(
                    f"Claude API so'rovi yuborilmoqda (Urinish {attempt}/{max_retries}, "
                    f"Savollar soni: {len(questions)})"
                )

                params = {
                    "model": self.model,
                    "max_tokens": 4000,
                    "system": CLAUDE_SYSTEM_PROMPT,
                    "messages": [{"role": "user", "content": user_content}],
                }
                if "claude-3" in self.model.lower():
                    params["temperature"] = 0.0  # Strict, deterministic answers for older models

                response = await self.client.messages.create(**params)

                # Track token metrics
                input_tokens = response.usage.input_tokens
                output_tokens = response.usage.output_tokens
                log.info(
                    f"Muvaffaqiyatli javob olindi. Tokenlar: "
                    f"Kirish={input_tokens}, Chiqish={output_tokens}"
                )

                # Extract response text
                text_response = "".join(block.text for block in response.content).strip()

                # Clean response (sometimes Claude wraps in code blocks even if told not to)
                cleaned_text = self._clean_json_response(text_response)

                # Parse and validate using Pydantic
                try:
                    parsed_json = json.loads(cleaned_text)
                    answer_list = AIAnswerList.model_validate(parsed_json)
                    
                    # Log tokens used to the answer objects for stats tracking
                    for ans in answer_list.answers:
                        # Distribute tokens across answers for granular tracking
                        pass
                        
                    return answer_list.answers

                except Exception as parse_err:
                    log.error(
                        f"Urinish {attempt}: JSON tahlil xatosi: {parse_err}. "
                        f"Qaytarilgan matn: {text_response[:500]}..."
                    )
                    if attempt == max_retries:
                        raise ValueError(f"Claude JSON formatini buzaverdi: {parse_err}")

            except RateLimitError as e:
                log.warning(
                    f"Urinish {attempt}: Rate Limit (429) yuzaga keldi. "
                    f"{delay} soniyadan keyin qayta urinib ko'riladi. Tafsilot: {e}"
                )
            except APIStatusError as e:
                # 500/503 etc.
                if e.status_code in (500, 502, 503, 504):
                    log.warning(
                        f"Urinish {attempt}: Claude Server Xatoligi ({e.status_code}). "
                        f"{delay} soniyadan keyin qayta uriniladi."
                    )
                else:
                    log.error(f"Urinish {attempt}: API status xatosi ({e.status_code}): {e}")
                    if attempt == max_retries:
                        raise
            except APIError as e:
                log.error(f"Urinish {attempt}: Umumiy API xatoligi: {e}")
                if attempt == max_retries:
                    raise
            except Exception as e:
                log.error(f"Urinish {attempt}: Kutilmagan xatolik: {e}")
                if attempt == max_retries:
                    raise

            # Apply backoff delay with random jitter
            jitter = random.uniform(0.0, 1.0)
            await asyncio.sleep(delay + jitter)
            delay *= backoff_factor

        raise RuntimeError("Claude resolver barcha urinishlarda muvaffaqiyatsiz bo'ldi.")

    def _clean_json_response(self, text: str) -> str:
        """
        Clean common markdown wrapper clutter from JSON response.
        """
        text = text.strip()
        # Remove ```json ... ```
        if text.startswith("```"):
            # Find first line and last line
            lines = text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        
        # Sometimes Claude puts prefix explanations like "Here is the JSON:"
        if not text.startswith("{") and "{" in text:
            text = text[text.find("{"):]
        if not text.endswith("}") and "}" in text:
            text = text[:text.rfind("}") + 1]

        return text
