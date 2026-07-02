"""Classic `? question / + correct / = wrong` TXT format generator.

Ported from the Streamlit parser tab (original app/ui/streamlit_app.py);
kept byte-identical to that download output.
"""
from __future__ import annotations

from typing import Iterable

from app.models.question import ParsedQuestion


def to_classic_txt(questions: Iterable[ParsedQuestion]) -> str:
    lines = []
    for q in questions:
        lines.append(f"? {q.q}")
        for idx, opt in enumerate(q.o):
            lines.append(f"+ {opt}" if idx == q.c else f"= {opt}")
        lines.append("")
    return "\n".join(lines)
