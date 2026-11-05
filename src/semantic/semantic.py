"""
DataLang semantic analyzer.

Walks a parsed Program and, together with the symbol table, checks that
the program is logically meaningful:

* After LOAD, inspect the CSV schema and record column names and types.
* SELECT, FILTER, and PLOT (AST node PlotStmt / keyword VISUALIZE) refer
  only to loaded datasets and existing columns.
* FILTER comparisons use compatible types and applicable operators.
* Visualization columns exist and are valid for the chosen chart type.
* Aggregates validate target/key types and advance the dataset's output schema.
* Sorting checks the current schema and preserves its column names and types.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Callable, List, Optional, Union

from src.ast import (
    AggregateStmt,
    BinaryCondition,
    Comparison,
    Condition,
    FilterStmt,
    LoadStmt,
    PlotStmt,
    Program,
    SelectStmt,
    SortStmt,
    Statement,
    UnaryCondition,
)
from src.symbol_table.symbol_table import (
    INTEGER,
    NUMERIC,
    STRING,
    DatasetSchema,
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

# Called after validation, with the statement's dataset and independent values.
StatementObserver = Callable[
    [Statement, Optional[str], Optional[DatasetSchema], Optional[DatasetSchema], bool],
    None,
]


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

    def analyze(
        self, program: Program, *, on_statement: Optional[StatementObserver] = None,
    ) -> SymbolTable:
        """
        Run semantic checks on `program`.

        If supplied, ``on_statement`` observes each completed check, including
        failures, with immutable before/after schemas for the named dataset.
        Checks validate before committing changes, so a failed statement has
        the same before/after schema. No schema propagation runs in observers.

        Returns:
            The populated symbol table if the program is valid.

        Raises:
            SemanticAnalysisError: If any semantic errors were found.
        """
        self.errors = []
        self.symbol_table = SymbolTable()

        for statement in program.statements:
            dataset_name = (
                statement.variable if isinstance(statement, LoadStmt)
                else statement.dataset if isinstance(statement, FilterStmt)
                else getattr(statement, "source", None)
            )
            before = (
                self.symbol_table.snapshot_dataset(dataset_name)
                if on_statement is not None and dataset_name is not None else None
            )
            error_count = len(self.errors)
            if isinstance(statement, LoadStmt):
                self._check_load(statement)
            elif isinstance(statement, SelectStmt):
                self._check_select(statement)
            elif isinstance(statement, FilterStmt):
                self._check_filter(statement)
            elif isinstance(statement, PlotStmt):
                self._check_plot(statement)
            elif isinstance(statement, AggregateStmt):
                self._check_aggregate(statement)
            elif isinstance(statement, SortStmt):
                self._check_sort(statement)
            else:
                self._error(
                    f"Unsupported statement type '{type(statement).__name__}'",
                    getattr(statement, "line", None),
                    getattr(statement, "column", None),
                )
            if on_statement is not None:
                after = (
                    self.symbol_table.snapshot_dataset(dataset_name)
                    if dataset_name is not None else None
                )
                on_statement(statement, dataset_name, before, after, len(self.errors) == error_count)

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
        except (ValueError, OSError, UnicodeError, csv.Error) as exc:
            self._error(
                f"Cannot load dataset '{stmt.variable}' from '{stmt.file_path}': {exc}",
                stmt.line, stmt.column,
            )
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
        valid = [
            self._require_column(stmt.source, column_name, stmt.line, stmt.column, allow_ambiguous=True)
            for column_name in stmt.columns
        ]
        if all(valid):
            input_order = self.symbol_table.lookup(stmt.source).column_order
            # Projection preserves pandas' existing expansion of repeated
            # names: each requested name selects every matching input field.
            output_order = [name for requested in stmt.columns for name in input_order if name == requested]
            columns = {
                name: self.symbol_table.lookup_column(stmt.source, name).data_type
                for name in stmt.columns
            }
            self.symbol_table.replace_columns(stmt.source, columns, output_order)

    def _check_sort(self, stmt: SortStmt) -> None:
        if not self._require_loaded_dataset(stmt.source, stmt.line, stmt.column):
            return
        if not self._require_column(stmt.source, stmt.column_name, stmt.line, stmt.column):
            return
        column = self.symbol_table.lookup_column(stmt.source, stmt.column_name)
        if column.data_type not in {INTEGER, NUMERIC, STRING}:
            self._error(
                f"SORT cannot order column '{stmt.column_name}' of type {column.data_type}",
                stmt.line, stmt.column,
            )
            return
        self.symbol_table.statement_schemas[id(stmt)] = {
            name: symbol.data_type
            for name, symbol in self.symbol_table.lookup(stmt.source).columns.items()
        }

    def _check_aggregate(self, stmt: AggregateStmt) -> None:
        if not self._require_loaded_dataset(stmt.source, stmt.line, stmt.column):
            return
        if stmt.function not in {"SUM", "AVG", "COUNT", "MIN", "MAX"}:
            self._error(f"Unsupported aggregate function '{stmt.function}'", stmt.line, stmt.column)
            return
        valid = self._require_column(stmt.source, stmt.column_name, stmt.line, stmt.column)
        if stmt.group_by is not None:
            valid = self._require_column(stmt.source, stmt.group_by, stmt.line, stmt.column) and valid
        if not valid:
            return
        target = self.symbol_table.lookup_column(stmt.source, stmt.column_name)
        if stmt.function != "COUNT" and not is_numeric_type(target.data_type):
            self._error(
                f"{stmt.function} requires a numeric column: '{stmt.column_name}' is {target.data_type}",
                stmt.line, stmt.column,
            )
            return
        result_name = f"{stmt.function.lower()}_{stmt.column_name}"
        if result_name == stmt.group_by:
            self._error(f"Aggregate output name '{result_name}' conflicts with grouping column", stmt.line, stmt.column)
            return
        result_type = target.data_type
        if stmt.function == "COUNT":
            result_type = INTEGER
        elif stmt.function == "AVG":
            result_type = NUMERIC
        columns = {}
        if stmt.group_by is not None:
            columns[stmt.group_by] = self.symbol_table.lookup_column(stmt.source, stmt.group_by).data_type
        columns[result_name] = result_type
        self.symbol_table.statement_schemas[id(stmt)] = columns.copy()
        self.symbol_table.replace_columns(stmt.source, columns)

    # ------------------------------------------------------------------ #
    # FILTER
    # ------------------------------------------------------------------ #

    def _check_filter(self, stmt: FilterStmt) -> None:
        if not self._require_loaded_dataset(stmt.dataset, stmt.line, stmt.column):
            return
        try:
            self._check_condition(stmt.dataset, stmt.condition)
        except RecursionError:
            self._error(
                "FILTER condition nesting is too deep; simplify nested expressions",
                stmt.line, stmt.column,
            )

    def _check_condition(self, dataset: str, condition: Condition) -> None:
        if isinstance(condition, Comparison):
            self._check_comparison(dataset, condition)
        elif isinstance(condition, UnaryCondition):
            self._check_condition(dataset, condition.operand)
        elif isinstance(condition, BinaryCondition):
            self._check_condition(dataset, condition.left)
            self._check_condition(dataset, condition.right)

    def _check_comparison(self, dataset: str, comparison: Comparison) -> None:
        if not self._require_column(dataset, comparison.column_name, comparison.line, comparison.column):
            return
        column = self.symbol_table.lookup_column(dataset, comparison.column_name)

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

        if not self._require_column(stmt.source, stmt.column_name, stmt.line, stmt.column):
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
        allow_ambiguous: bool = False,
    ) -> bool:
        if self.symbol_table.column_exists(dataset, column_name):
            if not allow_ambiguous and self.symbol_table.lookup(dataset).column_order.count(column_name) > 1:
                self._error(
                    f"Column '{column_name}' is ambiguous in dataset '{dataset}'",
                    line, column,
                )
                return False
            return True
        self._error(
            f"Column '{column_name}' does not exist in dataset '{dataset}'",
            line,
            column,
        )
        return False

    def _error(self, message: str, line: Optional[int], column: Optional[int]) -> None:
        self.errors.append(SemanticError(message, line, column))
