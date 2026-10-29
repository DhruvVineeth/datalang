"""
DataLang execution engine.

Interprets IR sequentially. Runtime tables (T1, T2, ...) are stored in
memory as Pandas DataFrames. Data-analysis ops and visualization ops are
dispatched to separate modules so GROUP, SORT, aggregation, and plots can
be added without changing the interpreter loop.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional

import numpy as np
import pandas as pd

from src.interpreter.ir import (
    AggregateIR,
    BoolPred,
    ComparePred,
    FilterIR,
    GroupIR,
    IRInstr,
    IRPred,
    IRProgram,
    LoadIR,
    NotPred,
    PlotIR,
    SelectIR,
    SortIR,
)
from src.symbol_table.symbol_table import INTEGER, NUMERIC, STRING


_COMPARE: Dict[str, Callable] = {
    "EQ": lambda series, value: series == value,
    "NEQ": lambda series, value: series != value,
    "LT": lambda series, value: series < value,
    "GT": lambda series, value: series > value,
    "LE": lambda series, value: series <= value,
    "GE": lambda series, value: series >= value,
}

# Pandas 1.5 and 2.x expose this built-in array under different public names.
_NUMPY_BOOLEAN_ARRAY_TYPE = type(pd.Series([], dtype=bool).array)


class ExecutionError(Exception):
    """Raised when an IR instruction cannot be executed."""

    def __init__(self, message: str, line=None, column=None):
        self.message, self.line, self.column = message, line, column
        location = f" (line {line}" if line is not None else ""
        if location:
            location += f", column {column})" if column is not None else ")"
        super().__init__(message + location)


class DataAnalysisModule:
    """
    Pandas-backed implementations of tabular operations.

    LOAD / SELECT / FILTER / SORT and optional grouped aggregation are implemented.
    Standalone GROUP remains reserved.
    """

    def load(self, file_path: str) -> pd.DataFrame:
        try:
            return pd.read_csv(file_path)
        except FileNotFoundError as exc:
            raise ExecutionError(f"Cannot load CSV '{file_path}': file not found") from exc
        except pd.errors.ParserError as exc:
            raise ExecutionError(f"Cannot load CSV '{file_path}': {exc}") from exc

    def select(self, table: pd.DataFrame, columns: List[str]) -> pd.DataFrame:
        missing = [name for name in columns if name not in table.columns]
        if missing:
            raise ExecutionError(f"SELECT column(s) not in table: {', '.join(missing)}")
        return table.loc[:, columns].copy()

    def filter(self, table: pd.DataFrame, mask: pd.Series) -> pd.DataFrame:
        return table.loc[mask.fillna(False)].copy()

    def group(self, table: pd.DataFrame, column: str) -> pd.DataFrame:
        raise ExecutionError("GROUP is not implemented yet")

    def sort(
        self, table: pd.DataFrame, column: str, ascending: bool = True,
        column_type: Optional[str] = None,
    ) -> pd.DataFrame:
        """Stable order of all rows, with nulls last in either direction."""
        if column not in table.columns:
            raise ExecutionError(f"SORT column '{column}' is not in the current table")
        if not isinstance(table[column], pd.Series):
            raise ExecutionError(f"SORT column '{column}' is ambiguous")
        if column_type not in {INTEGER, NUMERIC, STRING}:
            raise ExecutionError("SORT requires a semantically validated column type")
        present = table[column].dropna()
        if column_type == STRING:
            if not all(isinstance(value, str) for value in present):
                raise ExecutionError(f"SORT requires a String runtime column: '{column}'")
        elif not present.empty and (
            not pd.api.types.is_numeric_dtype(present.dtype)
            or pd.api.types.is_bool_dtype(present.dtype)
        ):
            raise ExecutionError(f"SORT requires a numeric runtime column: '{column}'")
        return table.sort_values(
            by=column, ascending=ascending, kind="stable", na_position="last",
        ).copy()

    def aggregate(
        self,
        table: pd.DataFrame,
        func: str,
        column: str,
        group_by: Optional[str] = None,
        output_schema: Optional[Dict[str, str]] = None,
    ) -> pd.DataFrame:
        if func not in {"SUM", "AVG", "COUNT", "MIN", "MAX"}:
            raise ExecutionError(f"Unsupported aggregate function '{func}'")
        for name in [column] + ([group_by] if group_by is not None else []):
            if name not in table.columns:
                raise ExecutionError(f"AGGREGATE column '{name}' is not in the current table")
            if not isinstance(table[name], pd.Series):
                raise ExecutionError(f"AGGREGATE column '{name}' is ambiguous")
        result_name = f"{func.lower()}_{column}"
        if result_name == group_by:
            raise ExecutionError(f"Aggregate output name '{result_name}' conflicts with grouping column")
        expected_names = ([group_by] if group_by is not None else []) + [result_name]
        if output_schema is None or list(output_schema) != expected_names:
            raise ExecutionError("AGGREGATE requires a matching semantically validated output schema")
        if func != "COUNT" and (
            not pd.api.types.is_numeric_dtype(table[column].dtype)
            or pd.api.types.is_bool_dtype(table[column].dtype)
        ):
            raise ExecutionError(f"{func} requires a numeric runtime column: '{column}'")

        def reduce(values: pd.Series):
            present = values.dropna()
            if func == "COUNT":
                return len(present)
            if present.empty:
                return pd.NA
            if func == "SUM":
                return present.sum()
            if func == "AVG":
                return present.mean()
            if func == "MIN":
                return present.min()
            return present.max()

        # Explicit nullable dtypes preserve logical numeric types for null and
        # zero-row outputs; inference from result values alone cannot do this.
        dtypes = {INTEGER: "Int64", NUMERIC: "Float64", STRING: "string"}
        if any(data_type not in dtypes for data_type in output_schema.values()):
            raise ExecutionError("Unsupported aggregate output type")
        if group_by is None:
            return pd.DataFrame({
                result_name: pd.Series([reduce(table[column])], dtype=dtypes[output_schema[result_name]])
            })

        keys, results = [], []
        groups = table.groupby(group_by, sort=False, dropna=False, observed=True)[column]
        for key, values in groups:
            keys.append(key)
            results.append(reduce(values))
        return pd.DataFrame({
            group_by: pd.Series(keys, dtype=dtypes[output_schema[group_by]]),
            result_name: pd.Series(results, dtype=dtypes[output_schema[result_name]]),
        })


class VisualizationModule:
    """Single-column plots: category counts or numeric values by row position."""

    def __init__(self, show: bool = True):
        self.show = show

    def plot(self, table: pd.DataFrame, chart_type: str, column: str):
        if chart_type not in {"BAR", "LINE", "SCATTER"}:
            raise ExecutionError(f"Unsupported chart type '{chart_type}'")
        if column not in table.columns:
            raise ExecutionError(f"PLOT column '{column}' is not in the current table")
        values = table[column].dropna()
        if values.empty:
            raise ExecutionError(f"Cannot plot '{column}': no non-null values")
        if chart_type in {"LINE", "SCATTER"}:
            if not pd.api.types.is_numeric_dtype(values):
                raise ExecutionError(f"{chart_type} requires a numeric column: '{column}'")
            import numpy as np
            if not np.isfinite(values.to_numpy(dtype=float)).all():
                raise ExecutionError(f"Cannot plot '{column}': values must be finite")

        # Lazy import lets programs without visualizations run independently.
        import matplotlib.pyplot as plt

        figure, axes = plt.subplots()
        try:
            if chart_type == "BAR":
                counts = values.value_counts(sort=False)
                positions = range(len(counts))
                axes.bar(positions, counts.to_numpy())
                axes.set_xticks(list(positions), [str(value) for value in counts.index])
                axes.set_xlabel(column)
                axes.set_ylabel("Count")
            else:
                positions = [position for position, present in enumerate(table[column].notna()) if present]
                if chart_type == "LINE":
                    axes.plot(positions, values.to_numpy(), marker="o")
                else:
                    axes.scatter(positions, values.to_numpy())
                axes.set_xlabel("Row position")
                axes.set_ylabel(column)
            axes.set_title(f"{chart_type}: {column}")
            figure.tight_layout()
            if self.show:
                plt.show()
            return figure
        except Exception:
            plt.close(figure)
            raise


class ExecutionEngine:
    """
    Sequential IR interpreter.

    Maintains:
        tables:     temp id -> DataFrame (T1, T2, ...)
        bindings:   source dataset name -> current temp id
        last_output: most recently written temp id
    """

    def __init__(
        self,
        analysis: Optional[DataAnalysisModule] = None,
        visualization: Optional[VisualizationModule] = None,
        optimize: bool = True,
    ):
        self.analysis = analysis or DataAnalysisModule()
        self.visualization = visualization or VisualizationModule()
        self.optimize = optimize
        self.tables: Dict[str, pd.DataFrame] = {}
        self.bindings: Dict[str, str] = {}
        self.last_output: Optional[str] = None
        self._dispatch: Dict[type, Callable[[IRInstr], None]] = {
            LoadIR: self._exec_load,
            SelectIR: self._exec_select,
            FilterIR: self._exec_filter,
            GroupIR: self._exec_group,
            SortIR: self._exec_sort,
            AggregateIR: self._exec_aggregate,
            PlotIR: self._exec_plot,
        }

    def execute(self, program: IRProgram) -> Dict[str, pd.DataFrame]:
        self.tables = {}
        self.bindings = {}
        self.last_output = None

        for position, instr in enumerate(program.instructions, start=1):
            operation = getattr(instr, "op", type(instr).__name__)
            source_line = getattr(instr, "source_line", None)
            source_column = getattr(instr, "source_column", None)
            try:
                handler = self._dispatch.get(type(instr))
                if handler is None:
                    raise ExecutionError(f"No executor for IR op '{operation}'")
                handler(instr)
            except ExecutionError as exc:
                line = exc.line if exc.line is not None else source_line
                column = exc.column if exc.line is not None else source_column
                raise ExecutionError(f"Instruction {position} ({operation}): {exc.message}", line, column) from exc
            except Exception as exc:
                raise ExecutionError(
                    f"Instruction {position} ({operation}): {exc}",
                    source_line, source_column,
                ) from exc

        return self.tables

    def result(self) -> Optional[pd.DataFrame]:
        """The last table written by a data-analysis instruction, if any."""
        if self.last_output is None:
            return None
        return self.tables.get(self.last_output)

    def _require_table(self, table_id: str) -> pd.DataFrame:
        if table_id not in self.tables:
            raise ExecutionError(f"Runtime table '{table_id}' does not exist")
        return self.tables[table_id]

    def _store(
        self, table_id: Optional[str], frame: pd.DataFrame, source_table: Optional[str] = None,
    ) -> None:
        if table_id is None:
            return
        self.tables[table_id] = frame
        self.last_output = table_id
        if source_table is not None:
            for name, current in self.bindings.items():
                if current == source_table:
                    self.bindings[name] = table_id

    # ----- implemented ops ------------------------------------------------

    def _exec_load(self, instr: LoadIR) -> None:
        frame = self.analysis.load(instr.file_path)
        self._store(instr.output, frame)
        self.bindings[instr.name] = instr.output

    def _exec_select(self, instr: SelectIR) -> None:
        frame = self._require_table(instr.input)
        self._store(instr.output, self.analysis.select(frame, instr.columns), source_table=instr.input)

    def _exec_filter(self, instr: FilterIR) -> None:
        frame = self._require_table(instr.input)
        if instr.condition is None:
            raise ExecutionError("FILTER is missing a condition")
        mask = eval_predicate(
            frame, instr.condition,
            optimize=self.optimize and type(self.analysis) is DataAnalysisModule
            and type(frame) is pd.DataFrame,
        )
        self._store(instr.output, self.analysis.filter(frame, mask), source_table=instr.input)

    # ----- reserved standalone grouping and sort/aggregate dispatch --------

    def _exec_group(self, instr: GroupIR) -> None:
        frame = self._require_table(instr.input)
        self._store(instr.output, self.analysis.group(frame, instr.column))

    def _exec_sort(self, instr: SortIR) -> None:
        frame = self._require_table(instr.input)
        self._store(
            instr.output, self.analysis.sort(frame, instr.column, instr.ascending, instr.column_type),
            source_table=instr.input,
        )

    def _exec_aggregate(self, instr: AggregateIR) -> None:
        frame = self._require_table(instr.input)
        self._store(
            instr.output,
            self.analysis.aggregate(frame, instr.func, instr.column, instr.group_by, instr.output_schema),
            source_table=instr.input,
        )

    def _exec_plot(self, instr: PlotIR) -> None:
        frame = self._require_table(instr.input)
        self.visualization.plot(frame, instr.chart_type, instr.column)


def eval_predicate(table: pd.DataFrame, pred: IRPred, *, optimize: bool = True) -> pd.Series:
    """Evaluate a lowered FILTER condition to a boolean Series."""
    try:
        return _eval_predicate(table, pred, optimize=optimize)
    except ExecutionError as exc:
        if exc.line is not None:
            raise
        raise ExecutionError(
            exc.message, getattr(pred, "source_line", None), getattr(pred, "source_column", None),
        ) from exc
    except Exception as exc:
        raise ExecutionError(
            f"Cannot evaluate FILTER condition: {exc}",
            getattr(pred, "source_line", None), getattr(pred, "source_column", None),
        ) from exc


def _eval_predicate(table: pd.DataFrame, pred: IRPred, *, optimize: bool = True) -> pd.Series:
    if isinstance(pred, ComparePred):
        if pred.column not in table.columns:
            raise ExecutionError(f"FILTER column '{pred.column}' is not in the current table")
        compare = _COMPARE.get(pred.op)
        if compare is None:
            raise ExecutionError(f"Unsupported FILTER operator '{pred.op}'")
        try:
            return compare(table[pred.column], pred.value)
        except Exception as exc:
            operator = {"EQ": "==", "NEQ": "!=", "LT": "<", "GT": ">", "LE": "<=", "GE": ">="}[pred.op]
            raise ExecutionError(
                f"Cannot compare column '{pred.column}' using {operator} to {pred.value!r}: {exc}"
            ) from exc

    if isinstance(pred, NotPred):
        if optimize and pred.elide_double_not and type(pred) is NotPred and type(pred.operand) is NotPred:
            inner = pred.operand
            # Keep the inner NOT's error context, including for hand-built IR
            # whose operand has no location. Evaluate the operand exactly once.
            values = _with_predicate_location(
                inner, lambda: eval_predicate(table, inner.operand, optimize=optimize),
            )
            if _standard_boolean_mask(values):
                return values
            # Nonstandard masks retain both inversions and their original errors.
            return ~_with_predicate_location(inner, lambda: ~values)
        return ~eval_predicate(table, pred.operand, optimize=optimize)

    if isinstance(pred, BoolPred):
        left = eval_predicate(table, pred.left, optimize=optimize)
        right = eval_predicate(table, pred.right, optimize=optimize)
        if pred.op == "AND":
            return left & right
        if pred.op == "OR":
            return left | right
        raise ExecutionError(f"Unsupported boolean operator '{pred.op}'")

    raise ExecutionError(f"Unsupported predicate {type(pred).__name__}")


def _with_predicate_location(pred, evaluate):
    """Retain a skipped NOT node's ordinary exception context."""
    try:
        return evaluate()
    except ExecutionError as exc:
        if exc.line is not None:
            raise
        raise ExecutionError(exc.message, pred.source_line, pred.source_column) from exc
    except Exception as exc:
        raise ExecutionError(
            f"Cannot evaluate FILTER condition: {exc}", pred.source_line, pred.source_column,
        ) from exc


def _standard_boolean_mask(values) -> bool:
    if type(values) is not pd.Series:
        return False
    dtype = values.dtype
    if type(dtype) is type(np.dtype("bool")) and dtype == np.dtype("bool"):
        return type(values.array) is _NUMPY_BOOLEAN_ARRAY_TYPE
    return type(dtype) is pd.BooleanDtype and type(values.array) is pd.arrays.BooleanArray
