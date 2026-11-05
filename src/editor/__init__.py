"""Read-only integrations for DataLang editors."""

from src.editor.analysis import analyze_document
from src.editor.cursor import ActiveStatement, CursorAnalysis, analyze_cursor

__all__ = ["ActiveStatement", "CursorAnalysis", "analyze_cursor", "analyze_document"]
