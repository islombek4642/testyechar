"""
Parser format types and exceptions.
"""

from __future__ import annotations

from enum import Enum


class FormatType(str, Enum):
    """
    Supported test parsing formats.
    """

    AUTO = "AUTO"          # Auto-detect format based on content analysis
    CLASSIC = "CLASSIC"    # Classic format using ? + = !
    ABC = "ABC"            # Standard numbered/lettered tests (1. A) B) C))
    BLOCKS = "BLOCKS"      # Separator-based format (++++ / ====)
    GIFT = "GIFT"          # GIFT format: plain question, { = correct ~ wrong }
