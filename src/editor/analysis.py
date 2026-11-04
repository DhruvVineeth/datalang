"""Analyze an editor buffer without invoking the compiler driver or runtime.

Only lexing, parsing, semantic checks and CSV schema inference run here. CSVs
are read using the existing semantic analyzer; the document itself is never
read from disk. Locations follow the compiler's convention: one-based lines
and zero-based columns (Python character offsets, not UTF-16 offsets).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from src.lexer.lexer import Lexer, TokenType
from src.parser.parser import ParseError, Parser
from src.semantic.semantic import SemanticAnalysisError, SemanticAnalyzer


@dataclass(frozen=True)
class Diagnostic:
    """An error from one of the three analysis stages, without CLI formatting."""

    stage: Literal["lexical", "syntax", "semantic"]
    message: str
    line: int | None
    column: int | None
    severity: Literal["error"] = "error"


@dataclass(frozen=True)
class ColumnSchema:
    name: str
    data_type: str


@dataclass(frozen=True)
class DatasetSchema:
    """A dataset's final checked schema, retaining column order and repeats."""

    name: str
    file_path: str | None
    columns: tuple[ColumnSchema, ...]


@dataclass(frozen=True)
class AnalysisResult:
    """An independent snapshot associated with one document version.

    Lexical and syntax failures have no dataset schemas. On semantic failure,
    datasets contain the analyzer's last valid schema for each loaded dataset;
    failed statements do not replace those schemas. No mutable compiler state
    is exposed, and no analysis state is shared between calls.
    """

    document_path: str
    document_version: int
    diagnostics: tuple[Diagnostic, ...] = ()
    datasets: tuple[DatasetSchema, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.diagnostics


def analyze_document(
    text: str,
    document_path: str | Path,
    document_version: int,
) -> AnalysisResult:
    """Check current document text, stopping before IR generation.

    ``document_path`` is a filesystem path to the .dl document, which need not
    exist yet. It is resolved to an absolute path and its parent directory is
    used for relative LOAD paths, without changing the working directory.
    ``document_version`` is echoed unchanged so clients can discard stale
    results. All lexical errors are returned; parsing stops at its first error;
    semantic analysis collects errors using the existing analyzer's rules.

    This function prints nothing, writes no files, and performs no dataset
    transformations or plotting. CSV inspection uses the same inference as
    the CLI, including its file and schema diagnostics.
    """
    path = Path(document_path).resolve()
    tokens = Lexer(text).tokenize()
    diagnostics = tuple(
        Diagnostic("lexical", token.lexeme, token.line, token.column)
        for token in tokens
        if token.type == TokenType.ERROR
    )
    if diagnostics:
        return AnalysisResult(str(path), document_version, diagnostics)

    try:
        program = Parser(tokens).parse()
    except ParseError as exc:
        stage = "lexical" if exc.stage == "Lexical" else "syntax"
        diagnostic = Diagnostic(stage, exc.message, exc.line, exc.column)
        return AnalysisResult(str(path), document_version, (diagnostic,))

    analyzer = SemanticAnalyzer(source_dir=path.parent)
    try:
        analyzer.analyze(program)
    except SemanticAnalysisError as exc:
        diagnostics = tuple(
            Diagnostic("semantic", error.message, error.line, error.column)
            for error in exc.errors
        )

    datasets = tuple(
        DatasetSchema(
            name=dataset.name,
            file_path=dataset.file_path,
            columns=tuple(
                ColumnSchema(name, dataset.columns[name].data_type)
                for name in dataset.column_order
            ),
        )
        for dataset in analyzer.symbol_table.datasets()
    )
    return AnalysisResult(str(path), document_version, diagnostics, datasets)
