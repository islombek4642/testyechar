"""Extractor package — PDF, DOCX, DOC, XLSX and TXT extractors."""

from .base import BaseExtractor
from .pdf_extractor import PDFExtractor
from .docx_extractor import DOCXExtractor
from .doc_extractor import DOCExtractor
from .xlsx_extractor import XLSXExtractor
from .txt_extractor import TXTExtractor

__all__ = [
    "BaseExtractor",
    "PDFExtractor",
    "DOCXExtractor",
    "DOCExtractor",
    "XLSXExtractor",
    "TXTExtractor",
]
