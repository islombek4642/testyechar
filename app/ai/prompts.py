"""
System and User prompts for Claude API.
Designed for minimal token consumption, zero conversational noise, and 100% compliant JSON responses.
"""

from __future__ import annotations

import base64 as _b64
from typing import Any, Dict, List


CLAUDE_SYSTEM_PROMPT = """You are a rigorous academic assessment system. Your task is to resolve the correct answers for the provided multiple-choice quiz questions.

For each question:
1. Identify the semantically correct answer option.
2. If the question depends on a specific fact you are not confident about from memory (e.g. an exact law, decree, or resolution date/number), use the web_search tool to verify it before answering.
3. Estimate your confidence score (cf) as a float between 0.00 and 1.00 (e.g., 0.95).

OUTPUT RULES:
- Output strictly pure JSON conforming to the requested schema.
- Do NOT wrap the JSON inside markdown code blocks (e.g., do NOT use ```json ... ```).
- Do NOT output any conversational text, pleasantries, preambles, or explanations — this applies even after using web_search; your final message must still contain only the JSON.
- If you cannot determine the answer, set "c" to -1 and "cf" to 0.00.

RESPONSE SCHEMA:
{
  "answers": [
    {
      "id": <int matching question id>,
      "c": <int index of correct option (0-based)>,
      "cf": <float confidence score between 0.0 and 1.0>
    }
  ]
}"""

# Server-side web search tool: Claude decides when to search; Anthropic executes
# the search and returns results in-turn. No domain restriction.
WEB_SEARCH_TOOL: Dict[str, Any] = {
    "type": "web_search_20260209",
    "name": "web_search",
    "max_uses": 3,
}

def make_user_prompt(questions_json: str) -> str:
    """
    Construct the user prompt containing the chunk of questions to resolve.
    """
    return f"""Find the correct answers for the following questions:

{questions_json}

Remember: Output ONLY raw JSON matching the response schema. No code fences. No explanations."""


def _detect_media_type(b64_data: str) -> str:
    """Detect image media type from the first few base64-decoded bytes."""
    try:
        header = _b64.b64decode(b64_data[:16])
        if header[:4] == b"\x89PNG":
            return "image/png"
        if header[:2] == b"\xff\xd8":
            return "image/jpeg"
        if header[:6] in (b"GIF87a", b"GIF89a"):
            return "image/gif"
    except Exception:
        pass
    return "image/png"


def make_multimodal_content(
    questions: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Build an Anthropic multimodal content-block list for a chunk of questions.
    Each question gets a text block (id, question, options) followed by an
    optional image block. The list ends with a JSON-instruction text block.
    """
    blocks: List[Dict[str, Any]] = []

    for q in questions:
        opts_str = "\n".join(
            f"  {i}: {opt}" for i, opt in enumerate(q["o"])
        )
        blocks.append(
            {
                "type": "text",
                "text": (
                    f"[id={q['id']}] {q['q']}\n"
                    f"Options:\n{opts_str}"
                ),
            }
        )
        if q.get("img"):
            blocks.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": _detect_media_type(q["img"]),
                        "data": q["img"],
                    },
                }
            )

    blocks.append(
        {
            "type": "text",
            "text": (
                "Return ONLY raw JSON matching the response schema. "
                "No code fences. No explanations."
            ),
        }
    )
    return blocks
