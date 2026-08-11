"""Local OCR index database primitives. No OCR engine or UI dependencies."""

from .database import OCRDatabase
from .repository import OCRRepository

__all__ = ["OCRDatabase", "OCRRepository"]
