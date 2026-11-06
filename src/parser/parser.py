"""
DataLang Parser Implementation

A recursive-descent parser for the DataLang DSL that builds an Abstract Syntax
Tree (AST) from the token stream produced by the Lexer. The existing statement
forms are preserved:

    LOAD "<file>" AS <identifier> ;
    FILTER <identifier> WHERE <condition> ;
    SELECT <col_list> FROM <identifier> ;
    VISUALIZE <chart_type> OF <column> FROM <identifier> ;

Aggregation extends the statement grammar with:
    AGGREGATE <function>(<column>) FROM <identifier> [GROUP BY <column>] ;
Each statement contains one function and at most one grouping column.
Sorting adds SORT <column> [ASC|DESC] FROM <identifier> ; with contextual words.

Grammar Implemented
--------------------
(1)   Program        -> StatementList
(2-3) StatementList  -> Statement StatementList | Statement          (iterative)
(4-7) Statement      -> LoadStmt | SelectStmt | FilterStmt | VisualizeStmt | AggregateStmt | SortStmt
(8)   LoadStmt       -> LOAD STRING_LIT AS ID SEMI
(9)   SelectStmt     -> SELECT ColumnList FROM ID SEMI
(10)  FilterStmt     -> FILTER ID WHERE Condition SEMI
(11)  VisualizeStmt  -> VISUALIZE ChartType OF ID FROM ID SEMI
(12-15) ChartType    -> BAR | LINE | SCATTER | PIE
(16-17) ColumnList   -> ID COMMA ColumnList | ID                     (iterative)
(18)  Condition      -> OrExpr
(19-20) OrExpr       -> AndExpr OR OrExpr | AndExpr                  (iterative)
(21-22) AndExpr      -> UnaryExpr AND AndExpr | UnaryExpr            (iterative)
(23-24) UnaryExpr    -> NOT UnaryExpr | Comparison
(25)  Comparison     -> ID RelOp Value
(26-31) RelOp        -> EQ | NEQ | LT | GT | LE | GE
(32-34) Value        -> INT_LIT | FLOAT_LIT | STRING_LIT
       AggregateStmt -> AGGREGATE AggregateFunc LPAREN ID RPAREN FROM ID
                        (GROUP BY ID)? SEMI
       AggregateFunc -> SUM | AVG | COUNT | MIN | MAX
       SortStmt      -> SORT-word ID (ASC-word | DESC-word)? FROM ID SEMI
                       (SORT/ASC/DESC remain ID tokens outside their context)

Note on rule (11): the language specification's general form for VISUALIZE is
`VISUALIZE <chart_type> OF <column> FROM <identifier>` — a single column, not
a column list, distinguishing it from SELECT.
"""

from dataclasses import dataclass, field
import sys
from pathlib import Path
from typing import List, Optional, TypeVar, Union

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.lexer.lexer import Token, TokenType, Lexer
from src.source import SourceSpan


# ============================================================================
# ABSTRACT SYNTAX TREE (AST) NODE DEFINITIONS
# ============================================================================

@dataclass
class ASTNode:
    """Base class for all AST nodes. Carries source-location info for
    downstream error reporting (semantic analysis, IR generation, etc.)."""
    line: int
    column: int
    # Parsed statement ranges end just after their terminating semicolon.
    # Keep existing positional constructors and AST equality unchanged.
    end_line: Optional[int] = field(default=None, init=False, compare=False, repr=False)
    end_column: Optional[int] = field(default=None, init=False, compare=False, repr=False)
    # Optional metadata must not change positional constructors or AST equality.
    spans: dict[str, SourceSpan] = field(default_factory=dict, init=False, compare=False, repr=False)


@dataclass
class Program(ASTNode):
    """
    Rule (1): Program -> StatementList

    Attributes:
        statements: The top-level sequence of statements in the program.
    """
    statements: List['Statement']


@dataclass
class LoadStmt(ASTNode):
    """
    Rule (8): LoadStmt -> LOAD STRING_LIT AS ID SEMI

    Example:
        LOAD "sales.csv" AS sales;

    Attributes:
        file_path: The quoted file path (escape sequences already resolved).
        variable: The identifier the dataset is bound to.
    """
    file_path: str
    variable: str


@dataclass
class SelectStmt(ASTNode):
    """
    Rule (9): SelectStmt -> SELECT ColumnList FROM ID SEMI

    Example:
        SELECT Region, Revenue FROM sales;

    Attributes:
        columns: The list of column names to select.
        source: The dataset identifier the columns are selected from.
    """
    columns: List[str]
    source: str


@dataclass
class Comparison(ASTNode):
    """
    Rule (25): Comparison -> ID RelOp Value

    A single relational test, e.g. `Revenue > 1000`.

    Attributes:
        column_name: The column identifier being tested. (Named
            `column_name` rather than `column` to avoid clashing with the
            inherited `ASTNode.column` source-position field.)
        operator: The relational operator name ("EQ", "NEQ", "LT", "GT",
            "LE", "GE").
        value: The literal being compared against.
    """
    column_name: str
    operator: str
    value: 'Value'


@dataclass
class UnaryCondition(ASTNode):
    """
    Rule (23): UnaryExpr -> NOT UnaryExpr

    Attributes:
        operator: Always "NOT".
        operand: The condition being negated.
    """
    operator: str
    operand: 'Condition'


@dataclass
class BinaryCondition(ASTNode):
    """
    Rules (19-22): OrExpr -> AndExpr OR OrExpr, AndExpr -> UnaryExpr AND AndExpr

    Attributes:
        operator: "AND" or "OR".
        left: The left-hand condition.
        right: The right-hand condition.
    """
    operator: str
    left: 'Condition'
    right: 'Condition'


# Type alias for any node that can appear inside a WHERE clause
Condition = Union[Comparison, UnaryCondition, BinaryCondition]


@dataclass
class FilterStmt(ASTNode):
    """
    Rule (10): FilterStmt -> FILTER ID WHERE Condition SEMI

    Example:
        FILTER sales WHERE Region = "North" AND Revenue > 1000;

    Attributes:
        dataset: The identifier of the dataset being filtered.
        condition: The (possibly compound) condition tree from the WHERE
            clause.
    """
    dataset: str
    condition: Condition


@dataclass
class PlotStmt(ASTNode):
    """
    Rule (11): VisualizeStmt -> VISUALIZE ChartType OF ID FROM ID SEMI

    Example:
        VISUALIZE BAR OF Revenue FROM sales;

    Attributes:
        chart_type: One of "BAR", "LINE", "SCATTER", "PIE".
        column_name: The single column to visualize. (Named `column_name`
            rather than `column` to avoid clashing with the inherited
            `ASTNode.column` source-position field.)
        source: The dataset identifier the column is drawn from.
    """
    chart_type: str
    column_name: str
    source: str


@dataclass
class AggregateStmt(ASTNode):
    """One column reduction, optionally partitioned by a grouping column."""

    function: str
    column_name: str
    source: str
    group_by: Optional[str] = None


@dataclass
class SortStmt(ASTNode):
    """Stable single-column sorting, ascending unless DESC is specified."""

    column_name: str
    source: str
    ascending: bool = True


@dataclass
class Value(ASTNode):
    """
    Rules (32-34): Value -> INT_LIT | FLOAT_LIT | STRING_LIT

    Attributes:
        type: "INT", "FLOAT", or "STRING".
        literal: The parsed literal value.
    """
    type: str
    literal: Union[int, float, str]


# Type alias for top-level statements
Statement = Union[LoadStmt, SelectStmt, FilterStmt, PlotStmt, AggregateStmt, SortStmt]


_Node = TypeVar("_Node", bound=ASTNode)


def _with_spans(node: _Node, **tokens: Optional[Token]) -> _Node:
    node.spans = {
        name: token.span or SourceSpan.from_text(token.line, token.column, token.lexeme)
        for name, token in tokens.items() if token is not None
    }
    return node


# ============================================================================
# PARSER CLASS
# ============================================================================

class Parser:
    """
    Recursive-descent parser for DataLang.

    Construction Strategy:
    - Tokens are supplied by the Lexer.
    - The parser keeps a single cursor (self.position) into the token stream.
    - Each grammar rule has a corresponding _parse_* method.
    - Terminals are matched via _consume(); non-terminals recurse.
    - Left recursion in the grammar (StatementList, ColumnList, OrExpr,
      AndExpr) is rewritten iteratively, folding repeated operators into a
      left-associative chain of BinaryCondition nodes for OR/AND.

    Error Handling:
    - A ParseError is raised on the first syntax error (fail-fast).
    - Every error message includes the offending token's line and column.
    """

    def __init__(self, tokens: List[Token]):
        """
        Args:
            tokens: The token list produced by Lexer.tokenize(), including
                the trailing EOF token.
        """
        self.tokens = tokens
        self.position = 0

    # ------------------------------------------------------------------ #
    # Rule (1): Program -> StatementList
    # ------------------------------------------------------------------ #

    def parse(self) -> Program:
        """
        Parse the full token stream into a Program node.

        Returns:
            The root Program node of the AST.

        Raises:
            ParseError: If the input does not form a valid DataLang program.
        """
        first = self._current_token()
        try:
            statements = self._parse_statement_list()
        except RecursionError:
            self._error("Condition nesting is too deep; simplify nested expressions")

        if self._current_token().type != TokenType.EOF:
            self._error(
                f"Unexpected token after program: '{self._current_token().lexeme}'"
            )

        return Program(statements=statements, line=first.line, column=first.column)

    # ------------------------------------------------------------------ #
    # Rules (2-3): StatementList -> Statement StatementList | Statement
    # ------------------------------------------------------------------ #

    def _parse_statement_list(self) -> List[Statement]:
        """
        Iterative form: StatementList -> (Statement)*

        Returns:
            The list of parsed statements, in source order.
        """
        statements = []
        while self._current_token().type != TokenType.EOF:
            statement = self._parse_statement()
            terminator = self.tokens[self.position - 1]
            statement.end_line = terminator.line
            statement.end_column = terminator.column + len(terminator.lexeme)
            statements.append(statement)
        return statements

    # ------------------------------------------------------------------ #
    # Rules (4-7): Statement -> LoadStmt | SelectStmt | FilterStmt | VisualizeStmt
    # ------------------------------------------------------------------ #

    def _parse_statement(self) -> Statement:
        """
        Dispatch on the leading keyword to pick a statement rule.

        Returns:
            One of LoadStmt, SelectStmt, FilterStmt, PlotStmt, AggregateStmt, SortStmt.

        Raises:
            ParseError: If the current token does not start a valid
                statement.
        """
        token_type = self._current_token().type

        if token_type == TokenType.LOAD:
            return self._parse_load_stmt()
        elif token_type == TokenType.SELECT:
            return self._parse_select_stmt()
        elif token_type == TokenType.FILTER:
            return self._parse_filter_stmt()
        elif token_type == TokenType.VISUALIZE:
            return self._parse_visualize_stmt()
        elif token_type == TokenType.AGGREGATE:
            return self._parse_aggregate_stmt()
        elif token_type == TokenType.ID and self._current_token().lexeme.lower() == "sort":
            return self._parse_sort_stmt()
        else:
            self._error(
                "Expected statement (LOAD, SELECT, FILTER, VISUALIZE, AGGREGATE, or SORT), "
                f"got '{self._current_token().lexeme}'"
            )

    def _parse_sort_stmt(self) -> SortStmt:
        start = self._consume(TokenType.ID, "Expected 'SORT'")
        column = self._consume(TokenType.ID, "Expected a sorting column after 'SORT'")
        ascending = True
        direction = self._current_token()
        if direction.type == TokenType.ID and direction.lexeme.lower() in {"asc", "desc"}:
            ascending = self._advance().lexeme.lower() == "asc"
        self._consume(TokenType.FROM, "Expected 'FROM' after sorting column and optional ASC/DESC")
        source = self._consume(TokenType.ID, "Expected a dataset identifier after 'FROM'")
        self._consume(TokenType.SEMI, "Expected ';' to terminate SORT statement")
        return _with_spans(SortStmt(
            line=start.line, column=start.column, column_name=column.lexeme,
            source=source.lexeme, ascending=ascending,
        ), column_name=column, source=source)

    def _parse_aggregate_stmt(self) -> AggregateStmt:
        start = self._consume(TokenType.AGGREGATE, "Expected 'AGGREGATE'")
        function = self._current_token()
        functions = {TokenType.SUM, TokenType.AVG, TokenType.COUNT, TokenType.MIN, TokenType.MAX}
        if function.type not in functions:
            self._error("Expected aggregate function (SUM, AVG, COUNT, MIN, or MAX)")
        self._advance()
        self._consume(TokenType.LPAREN, "Expected '(' after aggregate function")
        column = self._consume(TokenType.ID, "Expected an aggregate column")
        self._consume(TokenType.RPAREN, "Expected ')' after aggregate column")
        self._consume(TokenType.FROM, "Expected 'FROM' after aggregate expression")
        source = self._consume(TokenType.ID, "Expected a dataset identifier after 'FROM'")
        group_by = None
        if self._current_token().type == TokenType.GROUP:
            self._advance()
            self._consume(TokenType.BY, "Expected 'BY' after 'GROUP'")
            group_by = self._consume(TokenType.ID, "Expected a grouping column after 'BY'")
        self._consume(TokenType.SEMI, "Expected ';' to terminate AGGREGATE statement")
        return _with_spans(AggregateStmt(
            line=start.line, column=start.column, function=function.type.name,
            column_name=column.lexeme, source=source.lexeme, group_by=group_by.lexeme if group_by else None,
        ), function=function, column_name=column, source=source, group_by=group_by)

    # ------------------------------------------------------------------ #
    # Rule (8): LoadStmt -> LOAD STRING_LIT AS ID SEMI
    # ------------------------------------------------------------------ #

    def _parse_load_stmt(self) -> LoadStmt:
        """
        Example: LOAD "sales.csv" AS sales;
        """
        start = self._current_token()

        self._consume(TokenType.LOAD, "Expected 'LOAD'")
        path_token = self._consume(
            TokenType.STRING_LIT, "Expected a quoted file path after LOAD"
        )
        self._consume(TokenType.AS, "Expected 'AS' after the file path")
        var_token = self._consume(
            TokenType.ID, "Expected a dataset identifier after 'AS'"
        )
        self._consume(TokenType.SEMI, "Expected ';' to terminate LOAD statement")

        return _with_spans(LoadStmt(
            file_path=path_token.literal,
            variable=var_token.lexeme,
            line=start.line,
            column=start.column,
        ), file_path=path_token, variable=var_token)

    # ------------------------------------------------------------------ #
    # Rule (9): SelectStmt -> SELECT ColumnList FROM ID SEMI
    # ------------------------------------------------------------------ #

    def _parse_select_stmt(self) -> SelectStmt:
        """
        Example: SELECT Region, Revenue FROM sales;
        """
        start = self._current_token()

        self._consume(TokenType.SELECT, "Expected 'SELECT'")
        column_start = self.position
        columns = self._parse_column_list()
        column_tokens = self.tokens[column_start:self.position:2]
        self._consume(TokenType.FROM, "Expected 'FROM' after column list")
        source_token = self._consume(
            TokenType.ID, "Expected a dataset identifier after 'FROM'"
        )
        self._consume(TokenType.SEMI, "Expected ';' to terminate SELECT statement")

        return _with_spans(SelectStmt(
            columns=columns,
            source=source_token.lexeme,
            line=start.line,
            column=start.column,
        ), source=source_token, **{f"columns[{i}]": token for i, token in enumerate(column_tokens)})

    # ------------------------------------------------------------------ #
    # Rule (10): FilterStmt -> FILTER ID WHERE Condition SEMI
    # ------------------------------------------------------------------ #

    def _parse_filter_stmt(self) -> FilterStmt:
        """
        Example: FILTER sales WHERE Region = "North" AND Revenue > 1000;
        """
        start = self._current_token()

        self._consume(TokenType.FILTER, "Expected 'FILTER'")
        dataset_token = self._consume(
            TokenType.ID, "Expected a dataset identifier after 'FILTER'"
        )
        self._consume(TokenType.WHERE, "Expected 'WHERE' after dataset identifier")
        condition = self._parse_condition()
        self._consume(TokenType.SEMI, "Expected ';' to terminate FILTER statement")

        return _with_spans(FilterStmt(
            dataset=dataset_token.lexeme,
            condition=condition,
            line=start.line,
            column=start.column,
        ), dataset=dataset_token)

    # ------------------------------------------------------------------ #
    # Rule (11): VisualizeStmt -> VISUALIZE ChartType OF ID FROM ID SEMI
    # ------------------------------------------------------------------ #

    def _parse_visualize_stmt(self) -> PlotStmt:
        """
        Example: VISUALIZE BAR OF Revenue FROM sales;
        """
        start = self._current_token()

        self._consume(TokenType.VISUALIZE, "Expected 'VISUALIZE'")
        chart_token = self._current_token()
        chart_type = self._parse_chart_type()
        self._consume(TokenType.OF, "Expected 'OF' after chart type")
        column_token = self._consume(
            TokenType.ID, "Expected a column identifier after 'OF'"
        )
        self._consume(TokenType.FROM, "Expected 'FROM' after column identifier")
        source_token = self._consume(
            TokenType.ID, "Expected a dataset identifier after 'FROM'"
        )
        self._consume(
            TokenType.SEMI, "Expected ';' to terminate VISUALIZE statement"
        )

        return _with_spans(PlotStmt(
            chart_type=chart_type,
            column_name=column_token.lexeme,
            source=source_token.lexeme,
            line=start.line,
            column=start.column,
        ), chart_type=chart_token, column_name=column_token, source=source_token)

    # ------------------------------------------------------------------ #
    # Rules (12-15): ChartType -> BAR | LINE | SCATTER | PIE
    # ------------------------------------------------------------------ #

    def _parse_chart_type(self) -> str:
        """
        Returns:
            "BAR", "LINE", "SCATTER", or "PIE".

        Raises:
            ParseError: If the current token is not a recognized chart type.
        """
        token_type = self._current_token().type
        mapping = {
            TokenType.BAR: "BAR",
            TokenType.LINE: "LINE",
            TokenType.SCATTER: "SCATTER",
            TokenType.PIE: "PIE",
        }
        if token_type in mapping:
            self._advance()
            return mapping[token_type]
        self._error(
            "Expected chart type (BAR, LINE, SCATTER, or PIE), got "
            f"'{self._current_token().lexeme}'"
        )

    # ------------------------------------------------------------------ #
    # Rules (16-17): ColumnList -> ID COMMA ColumnList | ID
    # ------------------------------------------------------------------ #

    def _parse_column_list(self) -> List[str]:
        """
        Iterative form: ColumnList -> ID (COMMA ID)*
        """
        columns = [self._consume(TokenType.ID, "Expected a column name").lexeme]

        while self._current_token().type == TokenType.COMMA:
            self._advance()
            columns.append(
                self._consume(
                    TokenType.ID, "Expected a column name after ','"
                ).lexeme
            )

        return columns

    # ------------------------------------------------------------------ #
    # Rule (18): Condition -> OrExpr
    # ------------------------------------------------------------------ #

    def _parse_condition(self) -> Condition:
        """Entry point into the condition grammar (WHERE clauses)."""
        return self._parse_or_expr()

    # ------------------------------------------------------------------ #
    # Rules (19-20): OrExpr -> AndExpr OR OrExpr | AndExpr
    # ------------------------------------------------------------------ #

    def _parse_or_expr(self) -> Condition:
        """
        Iterative, left-associative form: OrExpr -> AndExpr (OR AndExpr)*
        """
        start = self._current_token()
        left = self._parse_and_expr()

        while self._current_token().type == TokenType.OR:
            self._advance()
            right = self._parse_and_expr()
            left = BinaryCondition(
                operator="OR", left=left, right=right,
                line=start.line, column=start.column,
            )

        return left

    # ------------------------------------------------------------------ #
    # Rules (21-22): AndExpr -> UnaryExpr AND AndExpr | UnaryExpr
    # ------------------------------------------------------------------ #

    def _parse_and_expr(self) -> Condition:
        """
        Iterative, left-associative form: AndExpr -> UnaryExpr (AND UnaryExpr)*
        """
        start = self._current_token()
        left = self._parse_unary_expr()

        while self._current_token().type == TokenType.AND:
            self._advance()
            right = self._parse_unary_expr()
            left = BinaryCondition(
                operator="AND", left=left, right=right,
                line=start.line, column=start.column,
            )

        return left

    # ------------------------------------------------------------------ #
    # Rules (23-24): UnaryExpr -> NOT UnaryExpr | Comparison
    # ------------------------------------------------------------------ #

    def _parse_unary_expr(self) -> Condition:
        """NOT binds tighter than AND/OR and may nest (e.g. NOT NOT x)."""
        if self._current_token().type == TokenType.NOT:
            start = self._current_token()
            self._advance()
            operand = self._parse_unary_expr()
            return UnaryCondition(
                operator="NOT", operand=operand,
                line=start.line, column=start.column,
            )
        return self._parse_comparison()

    # ------------------------------------------------------------------ #
    # Rule (25): Comparison -> ID RelOp Value
    # ------------------------------------------------------------------ #

    def _parse_comparison(self) -> Comparison:
        """
        Example: Revenue > 1000
        """
        column_token = self._consume(
            TokenType.ID, "Expected a column identifier in condition"
        )
        operator = self._parse_relop()
        value = self._parse_value()

        return _with_spans(Comparison(
            column_name=column_token.lexeme,
            operator=operator,
            value=value,
            line=column_token.line,
            column=column_token.column,
        ), column_name=column_token)

    # ------------------------------------------------------------------ #
    # Rules (26-31): RelOp -> EQ | NEQ | LT | GT | LE | GE
    # ------------------------------------------------------------------ #

    def _parse_relop(self) -> str:
        """
        Returns:
            "EQ", "NEQ", "LT", "GT", "LE", or "GE".

        Note: the language specification lists '=' as the equality operator,
        but the current Lexer only emits TokenType.EQ for '==' (a bare '='
        is reported as a lexical ERROR token). This parser matches whatever
        lexeme the Lexer actually classifies as TokenType.EQ, so it will
        start accepting '=' automatically if the Lexer is ever updated to
        match the specification — no parser change needed.
        """
        token_type = self._current_token().type
        mapping = {
            TokenType.EQ: "EQ",
            TokenType.NEQ: "NEQ",
            TokenType.LT: "LT",
            TokenType.GT: "GT",
            TokenType.LE: "LE",
            TokenType.GE: "GE",
        }
        if token_type in mapping:
            self._advance()
            return mapping[token_type]
        self._error(
            "Expected a relational operator (==, !=, <, >, <=, >=), got "
            f"'{self._current_token().lexeme}'"
        )

    # ------------------------------------------------------------------ #
    # Rules (32-34): Value -> INT_LIT | FLOAT_LIT | STRING_LIT
    # ------------------------------------------------------------------ #

    def _parse_value(self) -> Value:
        """
        Returns:
            A Value node wrapping the literal's type and parsed contents.
        """
        token = self._current_token()

        type_mapping = {
            TokenType.INT_LIT: "INT",
            TokenType.FLOAT_LIT: "FLOAT",
            TokenType.STRING_LIT: "STRING",
        }

        if token.type in type_mapping:
            self._advance()
            return _with_spans(Value(
                type=type_mapping[token.type],
                literal=token.literal,
                line=token.line,
                column=token.column,
            ), literal=token)

        self._error(
            "Expected a value (integer, float, or string literal), got "
            f"'{token.lexeme}'"
        )

    # ------------------------------------------------------------------ #
    # UTILITY METHODS
    # ------------------------------------------------------------------ #

    def _current_token(self) -> Token:
        """Return the token at the cursor, or the trailing EOF token."""
        token = self.tokens[min(self.position, len(self.tokens) - 1)]
        if token.type == TokenType.ERROR:
            raise ParseError(token.lexeme, token.line, token.column, stage="Lexical", span=token.span)
        return token

    def _advance(self) -> Token:
        """Move the cursor forward one token and return the token passed."""
        token = self._current_token()
        if self.position < len(self.tokens) - 1:
            self.position += 1
        return token

    def _consume(self, expected_type: TokenType, error_message: str) -> Token:
        """
        Match the current token against expected_type and advance past it.

        Raises:
            ParseError: If the current token's type does not match.
        """
        current = self._current_token()
        if current.type != expected_type:
            actual = "end of input" if current.type == TokenType.EOF else repr(current.lexeme)
            self._error(f"{error_message}; got {actual}")
        return self._advance()

    def _error(self, message: str) -> None:
        """
        Raise a ParseError annotated with the current token's line/column.

        Raises:
            ParseError: Always.
        """
        token = self._current_token()
        raise ParseError(message, token.line, token.column, span=token.span)


class ParseError(Exception):
    """Raised when the parser encounters a syntax (or embedded lexical) error."""

    def __init__(self, message: str, line=None, column=None, stage="Syntax", *, span=None):
        self.message, self.line, self.column, self.stage = message, line, column, stage
        self.span = span
        location = f" at line {line}, column {column}" if line is not None else ""
        super().__init__(f"{stage} error{location}: {message}")


# ============================================================================
# PRETTY-PRINTING THE AST
# ============================================================================

def print_ast(node: ASTNode, indent: int = 0) -> None:
    """
    Recursively print an AST node and its children for debugging.

    Args:
        node: The AST node to print.
        indent: Current indentation depth.
    """
    prefix = "  " * indent

    if isinstance(node, Program):
        print(f"{prefix}Program")
        for stmt in node.statements:
            print_ast(stmt, indent + 1)

    elif isinstance(node, LoadStmt):
        print(f"{prefix}LoadStmt (file: {node.file_path!r}, as: {node.variable})")

    elif isinstance(node, SelectStmt):
        print(f"{prefix}SelectStmt (columns: {', '.join(node.columns)}, from: {node.source})")

    elif isinstance(node, FilterStmt):
        print(f"{prefix}FilterStmt (dataset: {node.dataset})")
        print_ast(node.condition, indent + 1)

    elif isinstance(node, PlotStmt):
        print(f"{prefix}PlotStmt (chart: {node.chart_type}, column: {node.column_name}, from: {node.source})")

    elif isinstance(node, AggregateStmt):
        grouping = f", group by: {node.group_by}" if node.group_by is not None else ""
        print(f"{prefix}AggregateStmt ({node.function}({node.column_name}), from: {node.source}{grouping})")

    elif isinstance(node, SortStmt):
        direction = "ASC" if node.ascending else "DESC"
        print(f"{prefix}SortStmt (column: {node.column_name}, order: {direction}, from: {node.source})")

    elif isinstance(node, Comparison):
        print(f"{prefix}Comparison ({node.column_name} {node.operator} {node.value.literal!r})")

    elif isinstance(node, UnaryCondition):
        print(f"{prefix}UnaryCondition ({node.operator})")
        print_ast(node.operand, indent + 1)

    elif isinstance(node, BinaryCondition):
        print(f"{prefix}BinaryCondition ({node.operator})")
        print_ast(node.left, indent + 1)
        print_ast(node.right, indent + 1)


# ============================================================================
# DEMO
# ============================================================================

def main():
    """Tokenize and parse the two valid example programs from the language
    specification, then attempt an invalid program to show error reporting."""

    # NOTE: the spec's examples use '=' for equality, but the current Lexer
    # only recognizes '==' as TokenType.EQ (a bare '=' is a lexical error).
    # '==' is used below so this demo runs against the Lexer as given.
    valid_programs = [
        '''LOAD "sales.csv" AS sales;
FILTER sales WHERE Region == "North" AND Revenue > 1000;
SELECT Region, Revenue FROM sales;
VISUALIZE BAR OF Revenue FROM sales;''',
        '''LOAD "students.csv" AS students;
FILTER students WHERE Grade >= 60 AND NOT Grade > 100;
VISUALIZE LINE OF Grade FROM students;''',
    ]

    for i, source in enumerate(valid_programs, start=1):
        print("=" * 70)
        print(f"VALID PROGRAM {i}")
        print("=" * 70)
        print(source)
        print()

        tokens = Lexer(source).tokenize()
        try:
            ast = Parser(tokens).parse()
            print_ast(ast)
            print("\n✓ Parsed successfully\n")
        except ParseError as e:
            print(f"\n✗ Unexpected parse failure: {e}\n")

    # Invalid: identifier missing before WHERE's comparison column
    invalid_source = 'FILTER sales WHERE > 1000;'
    print("=" * 70)
    print("INVALID PROGRAM")
    print("=" * 70)
    print(invalid_source)
    print()

    tokens = Lexer(invalid_source).tokenize()
    try:
        Parser(tokens).parse()
        print("Unexpectedly parsed without error!")
    except ParseError as e:
        print(f"✗ {e}")


if __name__ == "__main__":
    main()
