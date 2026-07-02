"""
[[img:path]] placeholder token utilities.

Image-bearing extractors (e.g. the DOCX table extractor) embed
``[[img:relative/path.png]]`` tokens directly into cell/paragraph text so
that downstream sub-parsers (Classic, ABC, Blocks, GIFT) see a normal
non-empty text line — a cell whose only content was an image is no longer
treated as empty.

``QuestionParser.parse()`` strips these tokens back out after the
sub-parser runs and moves the referenced paths onto
``RawQuestion.images`` / ``RawOption.images``.
"""

from __future__ import annotations

import re

_IMG_TOKEN_RE = re.compile(r"\[\[img:([^\]]+)\]\]")


def build_image_token(relative_path: str) -> str:
    """Build a ``[[img:path]]`` placeholder token for *relative_path*."""
    return f"[[img:{relative_path}]]"


def extract_image_tokens(text: str) -> tuple[str, list[str]]:
    """
    Strip all ``[[img:path]]`` tokens from *text*.

    Returns the cleaned text (tokens removed, surrounding whitespace
    collapsed and trimmed) and the list of extracted relative paths, in
    the order they appeared.
    """
    images = _IMG_TOKEN_RE.findall(text)
    cleaned = _IMG_TOKEN_RE.sub("", text)
    cleaned = re.sub(r"[ \t]+", " ", cleaned).strip()
    return cleaned, images
