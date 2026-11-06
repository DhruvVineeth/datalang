"""Token and grammar based context for an editor cursor, including unfinished input.

Only complete, parsed statements before the active statement reach semantics.
The active statement is probed with the strict parser but never executed or
semantically validated. No grammar recovery is used to advance dataset schemas.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from src.ast import Program
from src.editor.analysis import AnalysisResult, Diagnostic, SourceRange, _analyze_program
from src.lexer.lexer import Lexer, Token, TokenType
from src.parser.parser import ParseError, Parser
from src.symbol_table.symbol_table import DatasetSchema


_STATEMENTS = ("LOAD", "SELECT", "FILTER", "SORT", "AGGREGATE", "VISUALIZE")
_KEYWORDS = {TokenType[name] for name in (
    "AS", "FROM", "WHERE", "GROUP", "BY", "OF",
)}


@dataclass(frozen=True)
class ActiveStatement:
    statement_index: int
    source_range: SourceRange
    kind: str | None
    dataset_name: str | None
    input_schema: DatasetSchema | None
    is_complete: bool


@dataclass(frozen=True)
class CursorAnalysis:
    """Fresh cursor context and the checked, complete prefix of this buffer.

    ``schema_reliable`` is false after an earlier syntax/lexical error. In that
    case ``input_schema`` is None, even if the dataset name can be read from the
    active statement. ``dataset_names`` only lists datasets in the checked
    prefix; it never selects a default dataset. Keywords are grammar assistance,
    not an exhaustive completion list.
    """

    prefix: AnalysisResult
    line: int
    column: int
    active_statement: ActiveStatement | None
    schema_reliable: bool
    keywords: tuple[str, ...]
    dataset_names: tuple[str, ...]

    @property
    def input_schema(self) -> DatasetSchema | None:
        return self.active_statement.input_schema if self.active_statement else None

    @property
    def diagnostics(self) -> tuple[Diagnostic, ...]:
        return self.prefix.diagnostics


class _ContextParser(Parser):
    """Observe grammar terminals without relaxing any strict parser rule."""

    def __init__(self, tokens: list[Token]):
        super().__init__(tokens)
        self.dataset_name: str | None = None
        self.expected_type: TokenType | None = None
        self.keywords: tuple[str, ...] = ()
        self.is_complete = False

    def _consume(self, expected_type: TokenType, error_message: str) -> Token:
        self.expected_type = expected_type
        self.keywords = (expected_type.name,) if expected_type in _KEYWORDS else ()
        current = self.tokens[self.position]
        if current.type == expected_type:
            if (expected_type == TokenType.ID and self.position > 0
                    and self.tokens[self.position - 1].type in {
                        TokenType.FROM, TokenType.FILTER, TokenType.AS,
                    }):
                self.dataset_name = current.lexeme
            self.expected_type = None
            self.keywords = ()
        return super()._consume(expected_type, error_message)

    def _error(self, message: str) -> None:
        if self.expected_type is None:
            if self.position == 0:
                self.keywords = _STATEMENTS
            elif self.position == 1 and self.tokens[0].type == TokenType.AGGREGATE:
                self.keywords = ("SUM", "AVG", "COUNT", "MIN", "MAX")
            elif self.position == 1 and self.tokens[0].type == TokenType.VISUALIZE:
                self.keywords = ("BAR", "LINE", "SCATTER", "PIE")
        super()._error(message)


def _probe(tokens: list[Token]) -> tuple[_ContextParser, ParseError | None]:
    parser = _ContextParser(tokens)
    try:
        parser.is_complete = bool(parser.parse().statements)
    except ParseError as error:
        return parser, error
    return parser, None


def _diagnostic(error: ParseError) -> Diagnostic:
    stage = "lexical" if error.stage == "Lexical" else "syntax"
    return Diagnostic(stage, error.message, error.line, error.column,
                      end_line=error.span.end_line if error.span else None,
                      end_column=error.span.end_column if error.span else None)


def _offset(text: str, line: int, column: int) -> int:
    # Match the lexer: only '\n' advances the line, and columns count Python
    # characters. A CR in CRLF is not an additional editor column at line end.
    lines = text.split("\n")
    if line < 1 or line > len(lines) or column < 0:
        raise ValueError("cursor is outside the document")
    if column > len(lines[line - 1].removesuffix("\r")):
        raise ValueError("cursor is outside the document")
    return sum(len(part) + 1 for part in lines[:line - 1]) + column


def _position(token: Token) -> tuple[int, int]:
    return token.line, token.column


def _eof(line: int, column: int) -> Token:
    return Token(TokenType.EOF, "", None, line, column)


def _kind(token: Token) -> str | None:
    if token.type.name in _STATEMENTS:
        return token.type.name
    if token.type == TokenType.ID and token.lexeme.lower() == "sort":
        return "SORT"
    return None


def _prefix_context(tokens: list[Token]) -> tuple[_ContextParser, ParseError | None]:
    """Treat EOF and a keyword fragment at the cursor as unfinished grammar."""
    parser, error = _probe(tokens)
    if error is None:
        return parser, None
    current = tokens[parser.position]
    if current.type == TokenType.EOF:
        return parser, None
    if (current.type == TokenType.ERROR and current.lexeme.startswith("Unterminated string")
            and parser.position == len(tokens) - 2):
        return parser, None
    # A partially typed keyword, e.g. FRO|, must not become an earlier syntax
    # error. Only accept fragments of terminals the real grammar expects.
    if current.type == TokenType.ID and parser.position == len(tokens) - 2:
        cursor = _position(tokens[-1])
        if (current.line, current.column + len(current.lexeme)) == cursor:
            shorter, earlier_error = _probe(tokens[:-2] + [tokens[-1]])
            choices = shorter.keywords if len(tokens) > 2 else _STATEMENTS
            matches = tuple(word for word in choices if word.startswith(current.lexeme.upper()))
            if matches and (earlier_error is None
                            or shorter.tokens[shorter.position].type == TokenType.EOF):
                shorter.keywords = matches
                return shorter, None
    return parser, error


def analyze_cursor(
    text: str,
    document_path: str | Path,
    document_version: int,
    line: int,
    column: int,
) -> CursorAnalysis:
    """Analyze complete statements preceding a cursor and describe its context.

    Coordinates are one-based lines and zero-based Python character columns.
    The active statement may be incomplete, or complete with the cursor inside
    it. Its input comes only from the checked prefix of this text/version.
    SELECT may use a FROM dataset later in this same token-delimited statement,
    including a column editing hole immediately before FROM. Missing scope
    yields keyword/dataset assistance and no column schema.

    An earlier syntax/lexical error stops propagation. No dependent semantic
    diagnostics or active schema are produced beyond that point. Strict
    ``analyze_document`` and compilation retain their fail-fast behavior.
    """
    offset = _offset(text, line, column)
    cursor = (line, column)
    path = Path(document_path).resolve()
    tokens = Lexer(text).tokenize()
    cursor_tokens = Lexer(text[:offset]).tokenize()

    # Only SEMI tokens delimit statements: strings and comments can contain
    # arbitrary semicolons without creating a boundary here.
    start = 0
    statement_index = 0
    statements = []
    boundary_error = None
    for index, token in enumerate(tokens):
        if _position(token) >= cursor:
            break
        if token.type != TokenType.SEMI:
            continue
        if boundary_error is None:
            try:
                program = Parser(tokens[start:index + 1] + [_eof(token.line, token.column + 1)]).parse()
                statements.extend(program.statements)
            except ParseError as error:
                boundary_error = error
        start = index + 1
        statement_index += 1

    prefix = _analyze_program(Program(1, 0, statements), path, document_version)
    if boundary_error is not None:
        prefix = replace(prefix, diagnostics=prefix.diagnostics + (_diagnostic(boundary_error),))
    reliable = boundary_error is None
    dataset_names = tuple(dataset.name for dataset in prefix.datasets)

    first = tokens[start]
    if first.type == TokenType.EOF or _position(first) > cursor:
        return CursorAnalysis(prefix, line, column, None, reliable, _STATEMENTS, dataset_names)

    end = start
    while tokens[end].type not in {TokenType.SEMI, TokenType.EOF}:
        end += 1
    last = tokens[end]
    end_position = (last.line, last.column + 1) if last.type == TokenType.SEMI else _position(last)
    active_tokens = tokens[start:end + 1]
    if last.type == TokenType.SEMI:
        active_tokens = active_tokens + [_eof(*end_position)]
    prefix_tokens = [token for token in cursor_tokens if _position(token) >= _position(first)]
    # The cursor EOF is always retained, even when it equals the active start.
    grammar, active_error = _prefix_context(prefix_tokens)
    if active_error is not None and reliable:
        reliable = False
        prefix = replace(prefix, diagnostics=prefix.diagnostics + (_diagnostic(active_error),))

    scope, _ = _probe(active_tokens)
    is_complete = scope.is_complete
    kind = _kind(first)
    if (scope.dataset_name is None and kind == "SELECT" and active_error is None
            and grammar.expected_type == TokenType.ID):
        # A SELECT column slot may be empty at the cursor. Probe the actual
        # grammar with one placeholder; never fabricate/propagate an AST.
        insertion = next(i for i, token in enumerate(active_tokens) if _position(token) >= cursor)
        if active_tokens[insertion].type == TokenType.FROM:
            placeholder = Token(TokenType.ID, "__editor_column__", None, line, column)
            scope, _ = _probe(active_tokens[:insertion] + [placeholder] + active_tokens[insertion:])

    schema = next(
        (dataset for dataset in prefix.datasets if dataset.name == scope.dataset_name), None,
    ) if reliable else None
    keywords = grammar.keywords
    if (kind == "SELECT" and scope.dataset_name is None and active_error is None
            and not any(token.type == TokenType.FROM for token in prefix_tokens)):
        keywords = ("FROM",)
    active = ActiveStatement(
        statement_index=statement_index,
        source_range=SourceRange(first.line, first.column, *end_position),
        kind=kind,
        dataset_name=scope.dataset_name,
        input_schema=schema,
        is_complete=is_complete,
    )
    return CursorAnalysis(prefix, line, column, active, reliable, keywords, dataset_names)
