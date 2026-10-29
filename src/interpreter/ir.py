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

LOAD, SELECT, FILTER, SORT, AGGREGATE (with optional GROUP BY), and PLOT are
lowered from the validated AST. Standalone GROUP remains reserved.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional, Union

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
    source_line: Optional[int] = field(default=None, kw_only=True, compare=False)
    source_column: Optional[int] = field(default=None, kw_only=True, compare=False)

    def format(self) -> str:
        return f"{self.column} {_OP_LEXEME[self.op]} {_format_value(self.value)}"


@dataclass
class NotPred:
    operand: "IRPred"
    source_line: Optional[int] = field(default=None, kw_only=True, compare=False)
    source_column: Optional[int] = field(default=None, kw_only=True, compare=False)
    # Execution hint only: retain both nodes for display and error provenance.
    elide_double_not: bool = field(default=False, kw_only=True, compare=False, repr=False)

    def format(self) -> str:
        return f"NOT ({self.operand.format()})"


@dataclass
class BoolPred:
    op: str  # AND | OR
    left: "IRPred"
    right: "IRPred"
    source_line: Optional[int] = field(default=None, kw_only=True, compare=False)
    source_column: Optional[int] = field(default=None, kw_only=True, compare=False)

    def format(self) -> str:
        return f"({self.left.format()} {self.op} {self.right.format()})"


IRPred = Union[ComparePred, NotPred, BoolPred]


_OP_LEXEME = {
    "EQ": "==",
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
    source_line: Optional[int] = field(default=None, kw_only=True, compare=False)
    source_column: Optional[int] = field(default=None, kw_only=True, compare=False)

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
    """Stable sorting of a table by one semantically checked column."""

    input: str = ""
    column: str = ""
    ascending: bool = True
    column_type: Optional[str] = None

    def __init__(
        self, input: str, column: str, output: str, ascending: bool = True,
        column_type: Optional[str] = None,
    ):
        super().__init__(op="SORT", output=output)
        self.input = input
        self.column = column
        self.ascending = ascending
        self.column_type = column_type

    def format(self) -> str:
        order = "ASC" if self.ascending else "DESC"
        return f"SORT {self.column} {order}\n    {self.input} -> {self.output}"


@dataclass
class AggregateIR(IRInstr):
    """A validated reduction and the schema of its ordinary table result."""

    input: str = ""
    func: str = ""
    column: str = ""
    group_by: Optional[str] = None
    output_schema: Optional[dict[str, str]] = None

    def __init__(
        self,
        input: str,
        func: str,
        column: str,
        output: str,
        group_by: Optional[str] = None,
        output_schema: Optional[dict[str, str]] = None,
    ):
        super().__init__(op="AGGREGATE", output=output)
        self.input = input
        self.func = func
        self.column = column
        self.group_by = group_by
        self.output_schema = dict(output_schema) if output_schema is not None else None

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
        lines = []
        for instr in self.instructions:
            try:
                lines.append(instr.format())
            except RecursionError as exc:
                raise IRError(
                    "IR expression nesting is too deep to display",
                    instr.source_line, instr.source_column,
                ) from exc
        return "\n".join(lines)


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
            try:
                if isinstance(stmt, LoadStmt):
                    instruction = self._lower_load(stmt)
                elif isinstance(stmt, SelectStmt):
                    instruction = self._lower_select(stmt)
                elif isinstance(stmt, FilterStmt):
                    instruction = self._lower_filter(stmt)
                elif isinstance(stmt, PlotStmt):
                    instruction = self._lower_plot(stmt)
                elif isinstance(stmt, AggregateStmt):
                    instruction = self._lower_aggregate(stmt)
                elif isinstance(stmt, SortStmt):
                    instruction = self._lower_sort(stmt)
                else:
                    raise IRError(f"Cannot lower statement type {type(stmt).__name__}")
            except IRError as exc:
                raise IRError(exc.message, stmt.line, stmt.column) from exc
            except RecursionError as exc:
                raise IRError("Expression nesting is too deep for IR generation", stmt.line, stmt.column) from exc
            instruction.source_line, instruction.source_column = stmt.line, stmt.column
            instructions.append(instruction)

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

    def _lower_aggregate(self, stmt: AggregateStmt) -> AggregateIR:
        schema = self.symbol_table.statement_schemas.get(id(stmt))
        if schema is None:
            raise IRError("Aggregate must pass semantic analysis before IR generation")
        src = self._table_for(stmt.source)
        dest = self._fresh()
        self._current[stmt.source] = dest
        return AggregateIR(
            input=src, func=stmt.function, column=stmt.column_name,
            output=dest, group_by=stmt.group_by, output_schema=schema,
        )

    def _lower_sort(self, stmt: SortStmt) -> SortIR:
        schema = self.symbol_table.statement_schemas.get(id(stmt))
        if schema is None:
            raise IRError("SORT must pass semantic analysis before IR generation")
        src = self._table_for(stmt.source)
        dest = self._fresh()
        self._current[stmt.source] = dest
        return SortIR(
            input=src, column=stmt.column_name, output=dest,
            ascending=stmt.ascending, column_type=schema[stmt.column_name],
        )


def lower_condition(condition: Condition) -> IRPred:
    if isinstance(condition, Comparison):
        return ComparePred(
            column=condition.column_name,
            op=condition.operator,
            value=condition.value.literal,
            source_line=condition.line, source_column=condition.column,
        )
    if isinstance(condition, UnaryCondition):
        return NotPred(
            operand=lower_condition(condition.operand),
            source_line=condition.line, source_column=condition.column,
        )
    if isinstance(condition, BinaryCondition):
        return BoolPred(
            op=condition.operator,
            left=lower_condition(condition.left),
            right=lower_condition(condition.right),
            source_line=condition.line, source_column=condition.column,
        )
    raise IRError(f"Cannot lower condition type {type(condition).__name__}")


class IRError(Exception):
    """Raised when the AST cannot be lowered to IR."""

    def __init__(self, message: str, line=None, column=None):
        self.message, self.line, self.column = message, line, column
        location = f" at line {line}, column {column}" if line is not None else ""
        super().__init__(f"IR error{location}: {message}")
