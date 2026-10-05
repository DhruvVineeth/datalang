"""
DataLang intermediate representation.

The IR is a linear sequence of table-to-table instructions. Each instruction
reads named runtime tables and writes a new table (T1, T2, ...), matching
the architecture sketch:

    LOAD sales.csv -> T1
    SELECT product, revenue
        T1 -> T2
    FILTER revenue > 1000
        T2 -> T3

LOAD, SELECT, and FILTER are lowered from the AST today. GROUP, SORT,
aggregation, and PLOT instruction types are defined so those stages can be
wired in later without changing the execution loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional, Union

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
from src.symbol_table.symbol_table import SymbolTable


# ---------------------------------------------------------------------------
# Condition IR (independent of parser AST nodes)
# ---------------------------------------------------------------------------

@dataclass
class ComparePred:
    """column <op> value, e.g. revenue > 1000."""

    column: str
    op: str
    value: Any

    def format(self) -> str:
        return f"{self.column} {_OP_LEXEME[self.op]} {_format_value(self.value)}"


@dataclass
class NotPred:
    operand: "IRPred"

    def format(self) -> str:
        return f"NOT ({self.operand.format()})"


@dataclass
class BoolPred:
    op: str  # AND | OR
    left: "IRPred"
    right: "IRPred"

    def format(self) -> str:
        return f"({self.left.format()} {self.op} {self.right.format()})"


IRPred = Union[ComparePred, NotPred, BoolPred]


_OP_LEXEME = {
    "EQ": "=",
    "NEQ": "!=",
    "LT": "<",
    "GT": ">",
    "LE": "<=",
    "GE": ">=",
}


def _format_value(value: Any) -> str:
    if isinstance(value, str):
        return f'"{value}"'
    return str(value)


# ---------------------------------------------------------------------------
# Instructions
# ---------------------------------------------------------------------------

@dataclass
class IRInstr:
    """Base instruction. `output` is the destination runtime table id, if any."""

    op: str
    output: Optional[str] = None

    def format(self) -> str:
        return self.op


@dataclass
class LoadIR(IRInstr):
    file_path: str = ""
    name: str = ""  # dataset identifier from LOAD ... AS <name>

    def __init__(self, file_path: str, output: str, name: str):
        super().__init__(op="LOAD", output=output)
        self.file_path = file_path
        self.name = name

    def format(self) -> str:
        return f'LOAD "{self.file_path}" AS {self.name} -> {self.output}'


@dataclass
class SelectIR(IRInstr):
    input: str = ""
    columns: List[str] = field(default_factory=list)

    def __init__(self, input: str, columns: List[str], output: str):
        super().__init__(op="SELECT", output=output)
        self.input = input
        self.columns = columns

    def format(self) -> str:
        cols = ", ".join(self.columns)
        return f"SELECT {cols}\n    {self.input} -> {self.output}"


@dataclass
class FilterIR(IRInstr):
    input: str = ""
    condition: Optional[IRPred] = None

    def __init__(self, input: str, condition: IRPred, output: str):
        super().__init__(op="FILTER", output=output)
        self.input = input
        self.condition = condition

    def format(self) -> str:
        cond = self.condition.format() if self.condition is not None else ""
        return f"FILTER {cond}\n    {self.input} -> {self.output}"


@dataclass
class GroupIR(IRInstr):
    """Reserved for GROUP BY. Not lowered from the current grammar."""

    input: str = ""
    column: str = ""

    def __init__(self, input: str, column: str, output: str):
        super().__init__(op="GROUP", output=output)
        self.input = input
        self.column = column

    def format(self) -> str:
        return f"GROUP BY {self.column}\n    {self.input} -> {self.output}"


@dataclass
class SortIR(IRInstr):
    """Reserved for SORT. Not lowered from the current grammar."""

    input: str = ""
    column: str = ""
    ascending: bool = True

    def __init__(self, input: str, column: str, output: str, ascending: bool = True):
        super().__init__(op="SORT", output=output)
        self.input = input
        self.column = column
        self.ascending = ascending

    def format(self) -> str:
        order = "ASC" if self.ascending else "DESC"
        return f"SORT {self.column} {order}\n    {self.input} -> {self.output}"


@dataclass
class AggregateIR(IRInstr):
    """Reserved for SUM/AVG/COUNT/MIN/MAX. Not lowered from the current grammar."""

    input: str = ""
    func: str = ""
    column: str = ""
    group_by: Optional[str] = None

    def __init__(
        self,
        input: str,
        func: str,
        column: str,
        output: str,
        group_by: Optional[str] = None,
    ):
        super().__init__(op="AGGREGATE", output=output)
        self.input = input
        self.func = func
        self.column = column
        self.group_by = group_by

    def format(self) -> str:
        grouping = f" GROUP BY {self.group_by}" if self.group_by else ""
        return (
            f"AGGREGATE {self.func}({self.column}){grouping}\n"
            f"    {self.input} -> {self.output}"
        )


@dataclass
class PlotIR(IRInstr):
    """Visualization instruction lowered from VISUALIZE."""

    input: str = ""
    chart_type: str = ""
    column: str = ""

    def __init__(self, input: str, chart_type: str, column: str):
        super().__init__(op="PLOT", output=None)
        self.input = input
        self.chart_type = chart_type
        self.column = column

    def format(self) -> str:
        return f"PLOT {self.chart_type} {self.column}\n    {self.input} -> OUTPUT"


Instruction = Union[LoadIR, SelectIR, FilterIR, GroupIR, SortIR, AggregateIR, PlotIR]


@dataclass
class IRProgram:
    instructions: List[Instruction] = field(default_factory=list)

    def format(self) -> str:
        return "\n".join(instr.format() for instr in self.instructions)


# ---------------------------------------------------------------------------
# AST -> IR
# ---------------------------------------------------------------------------

class IRGenerator:
    """
    Lower a semantically valid Program into sequential IR.

    Dataset names from the source (LOAD ... AS sales) are mapped onto the
    latest temp table produced for that name, so later SELECT/FILTER ops
    pipeline: T1 -> T2 -> T3.
    """

    def __init__(self, symbol_table: SymbolTable):
        self.symbol_table = symbol_table
        self._counter = 0
        self._current: dict[str, str] = {}

    def generate(self, program: Program) -> IRProgram:
        self._counter = 0
        self._current = {}
        instructions: List[Instruction] = []

        for stmt in program.statements:
            if isinstance(stmt, LoadStmt):
                instructions.append(self._lower_load(stmt))
            elif isinstance(stmt, SelectStmt):
                instructions.append(self._lower_select(stmt))
            elif isinstance(stmt, FilterStmt):
                instructions.append(self._lower_filter(stmt))
            elif isinstance(stmt, PlotStmt):
                instructions.append(self._lower_plot(stmt))
            else:
                raise IRError(f"Cannot lower statement type {type(stmt).__name__}")

        return IRProgram(instructions=instructions)

    def _fresh(self) -> str:
        self._counter += 1
        return f"T{self._counter}"

    def _table_for(self, dataset: str) -> str:
        if dataset not in self._current:
            raise IRError(f"No runtime table bound to dataset '{dataset}'")
        return self._current[dataset]

    def _lower_load(self, stmt: LoadStmt) -> LoadIR:
        symbol = self.symbol_table.lookup(stmt.variable)
        path = symbol.file_path if symbol and symbol.file_path else stmt.file_path
        dest = self._fresh()
        self._current[stmt.variable] = dest
        return LoadIR(file_path=path, output=dest, name=stmt.variable)

    def _lower_select(self, stmt: SelectStmt) -> SelectIR:
        src = self._table_for(stmt.source)
        dest = self._fresh()
        self._current[stmt.source] = dest
        return SelectIR(input=src, columns=list(stmt.columns), output=dest)

    def _lower_filter(self, stmt: FilterStmt) -> FilterIR:
        src = self._table_for(stmt.dataset)
        dest = self._fresh()
        self._current[stmt.dataset] = dest
        return FilterIR(input=src, condition=lower_condition(stmt.condition), output=dest)

    def _lower_plot(self, stmt: PlotStmt) -> PlotIR:
        src = self._table_for(stmt.source)
        return PlotIR(input=src, chart_type=stmt.chart_type, column=stmt.column_name)


def lower_condition(condition: Condition) -> IRPred:
    if isinstance(condition, Comparison):
        return ComparePred(
            column=condition.column_name,
            op=condition.operator,
            value=condition.value.literal,
        )
    if isinstance(condition, UnaryCondition):
        return NotPred(operand=lower_condition(condition.operand))
    if isinstance(condition, BinaryCondition):
        return BoolPred(
            op=condition.operator,
            left=lower_condition(condition.left),
            right=lower_condition(condition.right),
        )
    raise IRError(f"Cannot lower condition type {type(condition).__name__}")


class IRError(Exception):
    """Raised when the AST cannot be lowered to IR."""
