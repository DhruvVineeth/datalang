"""SORT lowers validated current-table inputs into sequential IR."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.interpreter.ir import IRError, IRGenerator, SortIR
from src.lexer.lexer import Lexer
from src.main import compile_source
from src.parser.parser import Parser
from src.semantic.semantic import SemanticAnalyzer
from src.symbol_table.symbol_table import NUMERIC, SymbolTable


FIXTURES = Path(__file__).parent / "fixtures" / "phase3"


def compile_ir(source):
    program = Parser(Lexer(source).tokenize()).parse()
    symbols = SemanticAnalyzer(FIXTURES).analyze(program)
    return IRGenerator(symbols).generate(program)


@pytest.mark.parametrize("direction,ascending", [("", True), ("ASC", True), ("DESC", False)])
def test_sort_lowering_tracks_current_input(direction, ascending):
    ir = compile_ir(f'''LOAD "normal.csv" AS sales;
SELECT product, revenue FROM sales;
FILTER sales WHERE revenue >= 5;
AGGREGATE SUM(revenue) FROM sales GROUP BY product;
SORT sum_revenue {direction} FROM sales;
SELECT sum_revenue FROM sales;''')
    sort = ir.instructions[-2]
    assert isinstance(sort, SortIR)
    assert (sort.input, sort.output, sort.column) == ("T4", "T5", "sum_revenue")
    assert sort.ascending is ascending and sort.column_type == NUMERIC
    assert ir.instructions[-1].input == "T5"
    assert f"SORT sum_revenue {'ASC' if ascending else 'DESC'}\n    T4 -> T5" in ir.format()


def test_sort_does_not_change_other_dataset_bindings():
    ir = compile_ir('''LOAD "normal.csv" AS sales;
LOAD "nulls.csv" AS other;
SORT revenue DESC FROM sales;
SELECT product FROM other;
SORT product FROM sales;''')
    assert (ir.instructions[2].input, ir.instructions[2].output) == ("T1", "T3")
    assert (ir.instructions[3].input, ir.instructions[3].output) == ("T2", "T4")
    assert (ir.instructions[4].input, ir.instructions[4].output) == ("T3", "T5")


def test_unchecked_sort_cannot_be_lowered():
    program = Parser(Lexer('LOAD "normal.csv" AS sales; SORT revenue FROM sales;').tokenize()).parse()
    with pytest.raises(IRError, match="must pass semantic analysis"):
        IRGenerator(SymbolTable()).generate(program)


def test_sort_compile_only_does_not_execute(monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        raise AssertionError("Compile-only SORT reached execution")
    monkeypatch.setattr("src.main.ExecutionEngine.execute", forbidden)
    assert compile_source('LOAD "normal.csv" AS sales; SORT revenue DESC FROM sales;', FIXTURES, dump_ir=True, execute=False) == 0
    assert "SORT revenue DESC\n    T1 -> T2" in capsys.readouterr().out
