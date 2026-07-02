"""
Confidence classification engine.
Categorises AI answers into Trusted, Warning, and Manual Review tiers.
"""

from __future__ import annotations

from enum import Enum


class ConfidenceTier(str, Enum):
    """Tiers of trust for resolved answers."""

    TRUSTED = "TRUSTED"
    WARNING = "WARNING"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class ConfidenceClassifier:
    """
    Evaluates resolved confidence scores and tags them appropriately.
    """

    @staticmethod
    def classify(cf: float) -> ConfidenceTier:
        """
        Classify confidence:
        - cf >= 0.90: TRUSTED
        - cf between [0.70, 0.90): WARNING
        - cf < 0.70: MANUAL_REVIEW
        """
        if cf >= 0.90:
            return ConfidenceTier.TRUSTED
        elif cf >= 0.70:
            return ConfidenceTier.WARNING
        else:
            return ConfidenceTier.MANUAL_REVIEW

    @staticmethod
    def get_description(tier: ConfidenceTier, lang: str = "uz") -> str:
        """Get user-friendly description of the tier."""
        if lang == "uz":
            if tier == ConfidenceTier.TRUSTED:
                return "Ishonchli"
            elif tier == ConfidenceTier.WARNING:
                return "Ogohlantirish"
            else:
                return "Qo'lda tekshirish"
        
        # Fallback English
        if tier == ConfidenceTier.TRUSTED:
            return "Trusted"
        elif tier == ConfidenceTier.WARNING:
            return "Warning"
        else:
            return "Manual Review"
