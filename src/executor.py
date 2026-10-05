"""
DataLang execution engine.

Interprets IR sequentially. Runtime tables (T1, T2, ...) are stored in
memory as Pandas DataFrames. Data-analysis ops and visualization ops are
dispatched to separate modules so GROUP, SORT, aggregation, and plots can
be added without changing the interpreter loop.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional

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


_COMPARE: Dict[str, Callable] = {
    "EQ": lambda series, value: series == value,
    "NEQ": lambda series, value: series != value,
    "LT": lambda series, value: series < value,
    "GT": lambda series, value: series > value,
    "LE": lambda series, value: series <= value,
    "GE": lambda series, value: series >= value,
}


class ExecutionError(Exception):
    """Raised when an IR instruction cannot be executed."""


class DataAnalysisModule:
    """
    Pandas-backed implementations of tabular operations.

    LOAD / SELECT / FILTER are implemented. GROUP, SORT, and aggregation
    are stubs for later phases.
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

    def sort(self, table: pd.DataFrame, column: str, ascending: bool = True) -> pd.DataFrame:
        raise ExecutionError("SORT is not implemented yet")

    def aggregate(
        self,
        table: pd.DataFrame,
        func: str,
        column: str,
        group_by: Optional[str] = None,
    ) -> pd.DataFrame:
        raise ExecutionError("AGGREGATE is not implemented yet")


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
    ):
        self.analysis = analysis or DataAnalysisModule()
        self.visualization = visualization or VisualizationModule()
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
            handler = self._dispatch.get(type(instr))
            if handler is None:
                raise ExecutionError(f"No executor for IR op '{getattr(instr, 'op', type(instr))}'")
            try:
                handler(instr)
            except ExecutionError as exc:
                raise ExecutionError(f"Instruction {position} ({instr.op}): {exc}") from exc
            except Exception as exc:
                raise ExecutionError(f"Instruction {position} ({instr.op}): {exc}") from exc

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

    def _store(self, table_id: Optional[str], frame: pd.DataFrame) -> None:
        if table_id is None:
            return
        self.tables[table_id] = frame
        self.last_output = table_id

    # ----- implemented ops ------------------------------------------------

    def _exec_load(self, instr: LoadIR) -> None:
        frame = self.analysis.load(instr.file_path)
        self._store(instr.output, frame)
        self.bindings[instr.name] = instr.output

    def _exec_select(self, instr: SelectIR) -> None:
        frame = self._require_table(instr.input)
        self._store(instr.output, self.analysis.select(frame, instr.columns))

    def _exec_filter(self, instr: FilterIR) -> None:
        frame = self._require_table(instr.input)
        if instr.condition is None:
            raise ExecutionError("FILTER is missing a condition")
        mask = eval_predicate(frame, instr.condition)
        self._store(instr.output, self.analysis.filter(frame, mask))

    # ----- reserved ops ---------------------------------------------------

    def _exec_group(self, instr: GroupIR) -> None:
        frame = self._require_table(instr.input)
        self._store(instr.output, self.analysis.group(frame, instr.column))

    def _exec_sort(self, instr: SortIR) -> None:
        frame = self._require_table(instr.input)
        self._store(instr.output, self.analysis.sort(frame, instr.column, instr.ascending))

    def _exec_aggregate(self, instr: AggregateIR) -> None:
        frame = self._require_table(instr.input)
        self._store(
            instr.output,
            self.analysis.aggregate(frame, instr.func, instr.column, instr.group_by),
        )

    def _exec_plot(self, instr: PlotIR) -> None:
        frame = self._require_table(instr.input)
        self.visualization.plot(frame, instr.chart_type, instr.column)


def eval_predicate(table: pd.DataFrame, pred: IRPred) -> pd.Series:
    """Evaluate a lowered FILTER condition to a boolean Series."""
    if isinstance(pred, ComparePred):
        if pred.column not in table.columns:
            raise ExecutionError(f"FILTER column '{pred.column}' is not in the current table")
        compare = _COMPARE.get(pred.op)
        if compare is None:
            raise ExecutionError(f"Unsupported FILTER operator '{pred.op}'")
        return compare(table[pred.column], pred.value)

    if isinstance(pred, NotPred):
        return ~eval_predicate(table, pred.operand)

    if isinstance(pred, BoolPred):
        left = eval_predicate(table, pred.left)
        right = eval_predicate(table, pred.right)
        if pred.op == "AND":
            return left & right
        if pred.op == "OR":
            return left | right
        raise ExecutionError(f"Unsupported boolean operator '{pred.op}'")

    raise ExecutionError(f"Unsupported predicate {type(pred).__name__}")
