"""
DataLang semantic analyzer.

Walks a parsed Program and, together with the symbol table, checks that
the program is logically meaningful:

* After LOAD, inspect the CSV schema and record column names and types.
* SELECT, FILTER, and PLOT (AST node PlotStmt / keyword VISUALIZE) refer
  only to loaded datasets and existing columns.
* FILTER comparisons use compatible types and applicable operators.
* Visualization columns exist and are valid for the chosen chart type.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Union

from src.ast import (
    BinaryCondition,
    Comparison,
    Condition,
    FilterStmt,
    LoadStmt,
    PlotStmt,
    Program,
    SelectStmt,
    UnaryCondition,
)
from src.symbol_table.symbol_table import (
    STRING,
    SymbolTable,
    inspect_csv_schema,
    is_numeric_type,
)


# Relational operators that only make sense on numeric columns.
_ORDERING_OPERATORS = {"LT", "GT", "LE", "GE"}
_ORDERING_LEXEMES = {
    "LT": "<",
    "GT": ">",
    "LE": "<=",
    "GE": ">=",
    "EQ": "=",
    "NEQ": "!=",
}

# LINE and SCATTER require a numeric series. BAR may use any column.
_NUMERIC_CHARTS = {"LINE", "SCATTER"}


class SemanticError(Exception):
    """A single semantic error with an optional source location."""

    def __init__(self, message: str, line: Optional[int] = None, column: Optional[int] = None):
        self.message = message
        self.line = line
        self.column = column
        super().__init__(self.format())

    def format(self) -> str:
        if self.line is not None and self.column is not None:
            return (
                f"Semantic error at line {self.line}, column {self.column}: "
                f"{self.message}"
            )
        if self.line is not None:
            return f"Semantic error at line {self.line}: {self.message}"
        return f"Semantic error: {self.message}"


class SemanticAnalysisError(Exception):
    """Raised when analysis finishes with one or more semantic errors."""

    def __init__(self, errors: List[SemanticError]):
        self.errors = errors
        super().__init__("\n".join(error.format() for error in errors))


class SemanticAnalyzer:
    """
    Validate a DataLang AST against CSV-backed schema information.

    Args:
        source_dir: Directory used to resolve relative LOAD paths
            (typically the directory of the .dl source file).
    """

    def __init__(self, source_dir: Optional[Union[str, Path]] = None):
        self.source_dir = Path(source_dir) if source_dir is not None else Path.cwd()
        self.symbol_table = SymbolTable()
        self.errors: List[SemanticError] = []

    def analyze(self, program: Program) -> SymbolTable:
        """
        Run semantic checks on `program`.

        Returns:
            The populated symbol table if the program is valid.

        Raises:
            SemanticAnalysisError: If any semantic errors were found.
        """
        self.errors = []
        self.symbol_table = SymbolTable()

        for statement in program.statements:
            if isinstance(statement, LoadStmt):
                self._check_load(statement)
            elif isinstance(statement, SelectStmt):
                self._check_select(statement)
            elif isinstance(statement, FilterStmt):
                self._check_filter(statement)
            elif isinstance(statement, PlotStmt):
                self._check_plot(statement)
            else:
                self._error(
                    f"Unsupported statement type '{type(statement).__name__}'",
                    getattr(statement, "line", None),
                    getattr(statement, "column", None),
                )

        if self.errors:
            raise SemanticAnalysisError(self.errors)
        return self.symbol_table

    # ------------------------------------------------------------------ #
    # LOAD
    # ------------------------------------------------------------------ #

    def _check_load(self, stmt: LoadStmt) -> None:
        if self.symbol_table.has_dataset(stmt.variable):
            self._error(
                f"Dataset '{stmt.variable}' is already loaded",
                stmt.line,
                stmt.column,
            )
            return

        resolved = self._resolve_csv_path(stmt.file_path)
        try:
            columns, _order = inspect_csv_schema(str(resolved))
        except FileNotFoundError:
            self._error(
                f"Cannot load dataset '{stmt.variable}': file '{stmt.file_path}' not found",
                stmt.line,
                stmt.column,
            )
            return
        except (ValueError, OSError, UnicodeError) as exc:
            self._error(str(exc), stmt.line, stmt.column)
            return

        self.symbol_table.insert_dataset(stmt.variable, str(resolved), columns)

    def _resolve_csv_path(self, file_path: str) -> Path:
        path = Path(file_path)
        if path.is_absolute():
            return path
        return (self.source_dir / path).resolve()

    # ------------------------------------------------------------------ #
    # SELECT
    # ------------------------------------------------------------------ #

    def _check_select(self, stmt: SelectStmt) -> None:
        if not self._require_loaded_dataset(stmt.source, stmt.line, stmt.column):
            return
        for column_name in stmt.columns:
            self._require_column(stmt.source, column_name, stmt.line, stmt.column)

    # ------------------------------------------------------------------ #
    # FILTER
    # ------------------------------------------------------------------ #

    def _check_filter(self, stmt: FilterStmt) -> None:
        if not self._require_loaded_dataset(stmt.dataset, stmt.line, stmt.column):
            return
        self._check_condition(stmt.dataset, stmt.condition)

    def _check_condition(self, dataset: str, condition: Condition) -> None:
        if isinstance(condition, Comparison):
            self._check_comparison(dataset, condition)
        elif isinstance(condition, UnaryCondition):
            self._check_condition(dataset, condition.operand)
        elif isinstance(condition, BinaryCondition):
            self._check_condition(dataset, condition.left)
            self._check_condition(dataset, condition.right)

    def _check_comparison(self, dataset: str, comparison: Comparison) -> None:
        column = self.symbol_table.lookup_column(dataset, comparison.column_name)
        if column is None:
            self._error(
                f"Column '{comparison.column_name}' does not exist in dataset '{dataset}'",
                comparison.line,
                comparison.column,
            )
            return

        op = comparison.operator
        value_kind = comparison.value.type
        lexeme = _ORDERING_LEXEMES.get(op, op)

        if op in _ORDERING_OPERATORS:
            if not is_numeric_type(column.data_type):
                self._error(
                    f"Operator '{lexeme}' is not applicable to column "
                    f"'{comparison.column_name}' of type {column.data_type}",
                    comparison.line,
                    comparison.column,
                )
                return
            if value_kind == "STRING":
                self._error(
                    f"Incompatible types in FILTER: column '{comparison.column_name}' "
                    f"is {column.data_type} but the comparison value is a string",
                    comparison.line,
                    comparison.column,
                )
            return

        # Equality / inequality
        column_is_numeric = is_numeric_type(column.data_type)
        value_is_numeric = value_kind in ("INT", "FLOAT")
        value_is_string = value_kind == "STRING"

        if column_is_numeric and value_is_numeric:
            return
        if column.data_type == STRING and value_is_string:
            return

        value_label = {
            "INT": "integer",
            "FLOAT": "numeric",
            "STRING": "string",
        }.get(value_kind, value_kind.lower())
        self._error(
            f"Incompatible types in FILTER: column '{comparison.column_name}' "
            f"is {column.data_type} but the comparison value is {value_label}",
            comparison.line,
            comparison.column,
        )

    # ------------------------------------------------------------------ #
    # PLOT / VISUALIZE
    # ------------------------------------------------------------------ #

    def _check_plot(self, stmt: PlotStmt) -> None:
        if stmt.chart_type not in {"BAR", "LINE", "SCATTER"}:
            self._error(f"Unsupported chart type '{stmt.chart_type}'", stmt.line, stmt.column)
            return
        if not self._require_loaded_dataset(stmt.source, stmt.line, stmt.column):
            return

        column = self.symbol_table.lookup_column(stmt.source, stmt.column_name)
        if column is None:
            self._error(
                f"Invalid visualization column '{stmt.column_name}': "
                f"it does not exist in dataset '{stmt.source}'",
                stmt.line,
                stmt.column,
            )
            return

        if stmt.chart_type in _NUMERIC_CHARTS and not is_numeric_type(column.data_type):
            self._error(
                f"Invalid visualization column '{stmt.column_name}' for "
                f"{stmt.chart_type} chart: expected a numeric column, found {column.data_type}",
                stmt.line,
                stmt.column,
            )

    # ------------------------------------------------------------------ #
    # Shared checks
    # ------------------------------------------------------------------ #

    def _require_loaded_dataset(self, name: str, line: Optional[int], column: Optional[int]) -> bool:
        if self.symbol_table.has_dataset(name):
            return True
        self._error(
            f"Dataset '{name}' has not been loaded",
            line,
            column,
        )
        return False

    def _require_column(
        self,
        dataset: str,
        column_name: str,
        line: Optional[int],
        column: Optional[int],
    ) -> bool:
        if self.symbol_table.column_exists(dataset, column_name):
            return True
        self._error(
            f"Column '{column_name}' does not exist in dataset '{dataset}'",
            line,
            column,
        )
        return False

    def _error(self, message: str, line: Optional[int], column: Optional[int]) -> None:
        self.errors.append(SemanticError(message, line, column))
