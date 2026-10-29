"""Lowering contracts after semantic validation, without runtime execution."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.interpreter.ir import AggregateIR, FilterIR, IRError, IRGenerator, PlotIR, SelectIR
from src.lexer.lexer import Lexer
from src.main import compile_source
from src.parser.parser import Parser
from src.semantic.semantic import SemanticAnalyzer
from src.symbol_table.symbol_table import INTEGER, NUMERIC, STRING, SymbolTable


FIXTURES = Path(__file__).parent / "fixtures" / "phase3"


def compile_ir(source):
    program = Parser(Lexer(source).tokenize()).parse()
    symbols = SemanticAnalyzer(FIXTURES).analyze(program)
    return IRGenerator(symbols).generate(program)


def test_lower_aggregate_pipeline_uses_current_tables_and_schema():
    ir = compile_ir('''LOAD "normal.csv" AS sales;
SELECT product, revenue FROM sales;
FILTER sales WHERE revenue >= 5;
AGGREGATE SUM(revenue) FROM sales GROUP BY product;
FILTER sales WHERE sum_revenue > 0;
VISUALIZE LINE OF sum_revenue FROM sales;''')
    load, select, first_filter, aggregate, last_filter, plot = ir.instructions
    assert isinstance(select, SelectIR) and isinstance(first_filter, FilterIR)
    assert isinstance(aggregate, AggregateIR)
    assert (aggregate.input, aggregate.output, aggregate.func, aggregate.column, aggregate.group_by) == (
        "T3", "T4", "SUM", "revenue", "product",
    )
    assert aggregate.output_schema == {"product": STRING, "sum_revenue": NUMERIC}
    assert last_filter.input == "T4" and last_filter.output == "T5"
    assert isinstance(plot, PlotIR) and plot.input == "T5"
    assert "AGGREGATE SUM(revenue) GROUP BY product\n    T3 -> T4" in ir.format()


def test_repeated_aggregation_keeps_each_schema_and_dataset_binding():
    ir = compile_ir('''LOAD "nulls.csv" AS sales;
LOAD "normal.csv" AS other;
AGGREGATE SUM(revenue) FROM sales GROUP BY product;
AGGREGATE AVG(sum_revenue) FROM sales;
SELECT quantity FROM other;''')
    grouped, ungrouped, select = ir.instructions[2:]
    assert (grouped.input, grouped.output) == ("T1", "T3")
    assert (ungrouped.input, ungrouped.output, ungrouped.group_by) == ("T3", "T4", None)
    assert grouped.output_schema == {"product": STRING, "sum_revenue": INTEGER}
    assert ungrouped.output_schema == {"avg_sum_revenue": NUMERIC}
    assert select.input == "T2" and select.output == "T5"


def test_aggregate_cannot_be_lowered_with_an_unchecked_symbol_table():
    program = Parser(Lexer('LOAD "normal.csv" AS sales; AGGREGATE SUM(revenue) FROM sales;').tokenize()).parse()
    with pytest.raises(IRError, match="must pass semantic analysis"):
        IRGenerator(SymbolTable()).generate(program)


def test_compile_only_lowers_aggregation_without_executing(monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        raise AssertionError("Compile-only source reached execution")
    monkeypatch.setattr("src.main.ExecutionEngine.execute", forbidden)
    source = 'LOAD "normal.csv" AS sales; AGGREGATE SUM(revenue) FROM sales GROUP BY product;'
    assert compile_source(source, FIXTURES, dump_ir=True, execute=False) == 0
    output = capsys.readouterr().out
    assert "Semantic analysis passed." in output
    assert "AGGREGATE SUM(revenue) GROUP BY product" in output
