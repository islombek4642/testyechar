"""
Parser state-machine definition.

Defines the finite states and the transition logic used by the
:class:`QuestionParser` to consume lines one at a time.
"""

from __future__ import annotations

from enum import Enum, auto


class ParserState(Enum):
    """
    Finite states of the question parser.

    Transitions:
        WAITING_QUESTION ──(? marker)──▶ READING_OPTIONS
        READING_OPTIONS  ──(+ or = marker)──▶ READING_OPTIONS  (accumulate)
        READING_OPTIONS  ──(? marker)──▶ flush → READING_OPTIONS  (new Q)
        READING_OPTIONS  ──(EOF)──▶ flush → done
    """

    WAITING_QUESTION = auto()
    READING_OPTIONS = auto()
