"""Compiler source spans: one-based lines, zero-based Unicode code points."""

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceSpan:
    """A half-open range over raw source text (before string escape decoding)."""

    line: int
    column: int
    end_line: int
    end_column: int

    @classmethod
    def from_text(cls, line: int, column: int, text: str) -> "SourceSpan":
        lines = text.split("\n")
        return cls(line, column, line + len(lines) - 1,
                   column + len(text) if len(lines) == 1 else len(lines[-1]))
