"""
Application-wide configuration settings.

All tuneable parameters live here.  Import the singleton `settings` object
wherever configuration values are needed — never hard-code them elsewhere.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel


class Settings(BaseModel):
    """
    Centralised configuration.

    All paths are resolved relative to the project root so the app works
    regardless of where the user launches it from.
    """

    # ------------------------------------------------------------------
    # Paths
    # ------------------------------------------------------------------
    project_root: Path = Path(__file__).resolve().parents[2]
    data_dir: Path = Path(__file__).resolve().parents[2] / "data"
    logs_dir: Path = Path(__file__).resolve().parents[2] / "logs"
    output_dir: Path = Path(__file__).resolve().parents[2] / "output"
    images_dir: Path = Path(__file__).resolve().parents[2] / "output" / "images"

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------
    log_file: str = "parser.log"
    log_level: str = "DEBUG"
    log_max_bytes: int = 10 * 1024 * 1024  # 10 MB
    log_backup_count: int = 5

    # ------------------------------------------------------------------
    # Parser markers
    # ------------------------------------------------------------------
    # Characters that mark the beginning of each element type.
    # A list is used so future markers can be added without code changes.
    question_markers: list[str] = ["?"]
    correct_markers: list[str] = ["+", "*"]
    wrong_markers: list[str] = ["="]

    # ------------------------------------------------------------------
    # Validation limits
    # ------------------------------------------------------------------
    min_options: int = 2
    max_options: int = 6
    min_question_length: int = 3  # characters (after strip)

    # ------------------------------------------------------------------
    # Extraction
    # ------------------------------------------------------------------
    # PyMuPDF text extraction flags
    # TEXT_PRESERVE_WHITESPACE | TEXT_PRESERVE_LIGATURES
    pdf_extract_flags: int = 0  # 0 = plain text, best for structured docs

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------
    output_filename: str = "questions.json"
    json_indent: int | None = None  # None = compact

    # ------------------------------------------------------------------
    # Streamlit UI
    # ------------------------------------------------------------------
    app_title: str = "PDF Test Parser"
    app_version: str = "1.0.0"

    class Config:
        frozen = True

    def ensure_dirs(self) -> None:
        """Create all required directories if they don't exist."""
        for d in (self.data_dir, self.logs_dir, self.output_dir, self.images_dir):
            d.mkdir(parents=True, exist_ok=True)


# Singleton — import this everywhere
settings = Settings()
