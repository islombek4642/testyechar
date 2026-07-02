"""
Asynchronous chunking system for Claude quiz processing.
Groups questions into optimal payload sizes while preserving indexing IDs.
"""

from __future__ import annotations

import base64
from typing import Dict, Any, List

from app.models.question import RawQuestion
from app.ai.docx_parser import AIRawQuestion


class QuestionChunker:
    """
    Splits unresolved questions into chunks optimized for LLM token sizes.
    Default chunk size: 20-25 questions per payload.
    """

    def __init__(self, chunk_size: int = 25) -> None:
        self.chunk_size = chunk_size

    def chunk_questions(self, questions: List[RawQuestion]) -> List[List[Dict[str, Any]]]:
        """
        Convert a list of RawQuestions into structured dictionary lists grouped in chunks.
        Excludes correct indicators (+), only outputs question text and options list.
        """
        chunks: List[List[Dict[str, Any]]] = []
        current_chunk: List[Dict[str, Any]] = []

        for idx, q in enumerate(questions, start=1):
            q_dict = {
                "id": idx,
                "q": q.question_text,
                "o": [opt.text for opt in q.options],
            }
            current_chunk.append(q_dict)

            if len(current_chunk) >= self.chunk_size:
                chunks.append(current_chunk)
                current_chunk = []

        if current_chunk:
            chunks.append(current_chunk)

        return chunks

    def chunk_ai_questions(
        self, questions: List[AIRawQuestion]
    ) -> List[List[Dict[str, Any]]]:
        """
        Like chunk_questions() but accepts AIRawQuestion objects.
        Images are base64-encoded into the "img" key (None if absent).
        """
        chunks: List[List[Dict[str, Any]]] = []
        current_chunk: List[Dict[str, Any]] = []

        for idx, aq in enumerate(questions, start=1):
            img_b64 = (
                base64.b64encode(aq.image).decode("ascii") if aq.image else None
            )
            current_chunk.append(
                {
                    "id": idx,
                    "q": aq.question.question_text,
                    "o": [opt.text for opt in aq.question.options],
                    "img": img_b64,
                }
            )
            if len(current_chunk) >= self.chunk_size:
                chunks.append(current_chunk)
                current_chunk = []

        if current_chunk:
            chunks.append(current_chunk)

        return chunks
