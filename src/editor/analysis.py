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

from src.ast import Program, Statement
from src.lexer.lexer import Lexer, TokenType
from src.parser.parser import ParseError, Parser
from src.semantic.semantic import SemanticAnalysisError, SemanticAnalyzer
from src.symbol_table.symbol_table import ColumnSchema, DatasetSchema


@dataclass(frozen=True)
class Diagnostic:
    """An error from one of the three analysis stages, without CLI formatting."""

    stage: Literal["lexical", "syntax", "semantic"]
    message: str
    line: int | None
    column: int | None
    severity: Literal["error"] = "error"


@dataclass(frozen=True)
class SourceRange:
    """Half-open statement range, including its terminating semicolon."""

    start_line: int
    start_column: int
    end_line: int
    end_column: int

    def contains(self, line: int, column: int) -> bool:
        return (
            line >= 1 and column >= 0
            and (self.start_line, self.start_column) <= (line, column)
            < (self.end_line, self.end_column)
        )


@dataclass(frozen=True)
class StatementSchemaSnapshot:
    """Checked schema transition for one statement's named dataset.

    ``statement_index`` is zero-based and local to this document version.
    Missing/unloaded datasets have no schema. Invalid statements retain their
    input schema as output and set ``is_valid`` to false.
    """

    statement_index: int
    source_range: SourceRange
    dataset_name: str | None
    before: DatasetSchema | None
    after: DatasetSchema | None
    is_valid: bool


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
    statements: tuple[StatementSchemaSnapshot, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.diagnostics

    def statement_at(self, line: int, column: int) -> StatementSchemaSnapshot | None:
        """Find the containing statement; trivia outside statements returns None."""
        return next(
            (statement for statement in self.statements if statement.source_range.contains(line, column)),
            None,
        )

    def schema_at(
        self, line: int, column: int, *, phase: Literal["before", "after"] = "before",
    ) -> DatasetSchema | None:
        """Return the containing statement's dataset schema at its input/output.

        Input is the default so references use the columns available when that
        statement runs. LOAD has no input schema. Output of an invalid statement
        equals its input. Positions outside statements return None; no dataset
        is guessed in whitespace/comments between statements or at EOF.
        """
        if phase not in {"before", "after"}:
            raise ValueError("phase must be 'before' or 'after'")
        statement = self.statement_at(line, column)
        if statement is None:
            return None
        return statement.before if phase == "before" else statement.after


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

    return _analyze_program(program, path, document_version)


def _analyze_program(program: Program, path: Path, document_version: int) -> AnalysisResult:
    """Analyze an already parsed program through the shared semantic pass."""
    statements = []
    diagnostics = ()

    def record_statement(
        statement: Statement,
        dataset_name: str | None,
        before: DatasetSchema | None,
        after: DatasetSchema | None,
        is_valid: bool,
    ) -> None:
        # Parser statement ranges use token positions, including multiline
        # statements and same-line statements without scanning source text.
        assert statement.end_line is not None and statement.end_column is not None
        statements.append(StatementSchemaSnapshot(
            statement_index=len(statements),
            source_range=SourceRange(
                statement.line, statement.column, statement.end_line, statement.end_column,
            ),
            dataset_name=dataset_name,
            before=before,
            after=after,
            is_valid=is_valid,
        ))

    analyzer = SemanticAnalyzer(source_dir=path.parent)
    try:
        analyzer.analyze(program, on_statement=record_statement)
    except SemanticAnalysisError as exc:
        diagnostics = tuple(
            Diagnostic("semantic", error.message, error.line, error.column)
            for error in exc.errors
        )

    datasets = tuple(
        schema
        for dataset in analyzer.symbol_table.datasets()
        if (schema := analyzer.symbol_table.snapshot_dataset(dataset.name)) is not None
    )
    return AnalysisResult(str(path), document_version, diagnostics, datasets, tuple(statements))
