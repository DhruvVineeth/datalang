"""SORT checks the current dataset schema before lowering or execution."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.lexer.lexer import Lexer
from src.main import compile_source
from src.parser.parser import Parser
from src.semantic.semantic import SemanticAnalysisError, SemanticAnalyzer
from src.symbol_table.symbol_table import INTEGER, NUMERIC, STRING


FIXTURES = Path(__file__).parent / "fixtures" / "phase3"


def analyze(source):
    program = Parser(Lexer(source).tokenize()).parse()
    return program, SemanticAnalyzer(FIXTURES).analyze(program)


@pytest.mark.parametrize("column", ["revenue", "quantity", "product"])
@pytest.mark.parametrize("direction", ["", "ASC", "DESC"])
def test_sort_preserves_current_schema(column, direction):
    program, symbols = analyze(f'LOAD "normal.csv" AS sales; SORT {column} {direction} FROM sales;')
    expected = {"id": INTEGER, "product": STRING, "revenue": NUMERIC, "quantity": INTEGER}
    assert symbols.statement_schemas[id(program.statements[-1])] == expected
    assert {name: symbol.data_type for name, symbol in symbols.lookup("sales").columns.items()} == expected


@pytest.mark.parametrize("fragment,message", [
    ("SORT revenue FROM unknown;", "unknown.*has not been loaded"),
    ("SORT missing FROM sales;", "missing.*does not exist"),
    ("SELECT product FROM sales; SORT revenue FROM sales;", "revenue.*does not exist"),
    ("AGGREGATE SUM(revenue) FROM sales GROUP BY product; SORT revenue FROM sales;", "revenue.*does not exist"),
    ("AGGREGATE SUM(revenue) FROM sales; SORT product FROM sales;", "product.*does not exist"),
])
def test_sort_rejects_unavailable_columns(fragment, message):
    with pytest.raises(SemanticAnalysisError, match=message):
        analyze('LOAD "normal.csv" AS sales; ' + fragment)


def test_sort_snapshot_matches_each_input_schema():
    program, symbols = analyze('''LOAD "normal.csv" AS sales;
SORT revenue DESC FROM sales;
AGGREGATE SUM(revenue) FROM sales GROUP BY product;
SORT sum_revenue FROM sales;
SELECT sum_revenue FROM sales;''')
    assert list(symbols.statement_schemas[id(program.statements[1])]) == ["id", "product", "revenue", "quantity"]
    assert symbols.statement_schemas[id(program.statements[3])] == {"product": STRING, "sum_revenue": NUMERIC}
    assert list(symbols.lookup("sales").columns) == ["sum_revenue"]


@pytest.mark.parametrize("filename", ["empty.csv", "all_null.csv", "mixed.csv"])
def test_sort_accepts_empty_all_null_and_text_inferred_columns(filename):
    program, symbols = analyze(f'LOAD "{filename}" AS sales; SORT revenue FROM sales;')
    assert symbols.statement_schemas[id(program.statements[-1])]["revenue"] == STRING


def test_invalid_sort_stops_before_ir_or_runtime(monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid SORT reached a later stage")
    monkeypatch.setattr("src.main.IRGenerator.generate", forbidden)
    monkeypatch.setattr("src.main.ExecutionEngine.execute", forbidden)
    assert compile_source('LOAD "normal.csv" AS sales; SELECT product FROM sales; SORT revenue FROM sales;', FIXTURES) == 1
    output = capsys.readouterr().out
    assert "Semantic error at line 1, column" in output and "revenue" in output
