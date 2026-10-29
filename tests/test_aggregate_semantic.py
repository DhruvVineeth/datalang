"""Semantic validation and schema evolution before any IR execution."""

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
    symbols = SemanticAnalyzer(FIXTURES).analyze(program)
    return program, symbols


@pytest.mark.parametrize("function", ["SUM", "AVG", "COUNT", "MIN", "MAX"])
@pytest.mark.parametrize("column,input_type", [("revenue", NUMERIC), ("quantity", INTEGER)])
@pytest.mark.parametrize("grouped", [False, True])
def test_aggregate_output_schema(function, column, input_type, grouped):
    grouping = " GROUP BY product" if grouped else ""
    program, symbols = analyze(f'LOAD "normal.csv" AS sales; AGGREGATE {function}({column}) FROM sales{grouping};')
    dataset = symbols.lookup("sales")
    result_name = f"{function.lower()}_{column}"
    assert list(dataset.columns) == (["product", result_name] if grouped else [result_name])
    expected_type = INTEGER if function == "COUNT" else NUMERIC if function == "AVG" else input_type
    assert dataset.columns[result_name].data_type == expected_type
    assert dataset.file_path == str((FIXTURES / "normal.csv").resolve())
    assert symbols.statement_schemas[id(program.statements[-1])][result_name] == expected_type


@pytest.mark.parametrize("filename", ["normal.csv", "mixed.csv", "all_null.csv", "empty.csv"])
def test_count_accepts_strings_and_empty_columns(filename):
    _, symbols = analyze(f'LOAD "{filename}" AS sales; AGGREGATE COUNT(product) FROM sales GROUP BY product;')
    assert list(symbols.lookup("sales").columns) == ["product", "count_product"]
    assert symbols.lookup_column("sales", "count_product").data_type == INTEGER


@pytest.mark.parametrize("function", ["SUM", "AVG", "MIN", "MAX"])
@pytest.mark.parametrize("filename,column", [
    ("normal.csv", "product"), ("mixed.csv", "revenue"),
    ("all_null.csv", "revenue"), ("empty.csv", "revenue"),
])
def test_numeric_functions_reject_string_schema(function, filename, column):
    with pytest.raises(SemanticAnalysisError, match=rf"{function} requires a numeric column"):
        analyze(f'LOAD "{filename}" AS sales; AGGREGATE {function}({column}) FROM sales;')


@pytest.mark.parametrize("fragment,message", [
    ("AGGREGATE SUM(revenue) FROM unknown;", "has not been loaded"),
    ("AGGREGATE SUM(missing) FROM sales;", "missing.*does not exist"),
    ("AGGREGATE SUM(revenue) FROM sales GROUP BY missing;", "missing.*does not exist"),
    ("SELECT product FROM sales; AGGREGATE SUM(revenue) FROM sales;", "revenue.*does not exist"),
    ("SELECT product FROM sales; FILTER sales WHERE revenue > 1;", "revenue.*does not exist"),
    ("AGGREGATE SUM(revenue) FROM sales; SELECT product FROM sales;", "product.*does not exist"),
    ("AGGREGATE SUM(revenue) FROM sales; FILTER sales WHERE revenue > 1;", "revenue.*does not exist"),
    ("AGGREGATE SUM(revenue) FROM sales; VISUALIZE LINE OF revenue FROM sales;", "Invalid visualization column"),
])
def test_invalid_current_schema(fragment, message):
    with pytest.raises(SemanticAnalysisError, match=message):
        analyze('LOAD "normal.csv" AS sales; ' + fragment)


def test_generated_name_collision():
    with pytest.raises(SemanticAnalysisError, match="sum_revenue.*conflicts"):
        analyze('LOAD "collision.csv" AS sales; AGGREGATE SUM(revenue) FROM sales GROUP BY sum_revenue;')


def test_schemas_are_snapshotted_for_repeated_aggregation():
    program, symbols = analyze('''LOAD "nulls.csv" AS sales;
AGGREGATE SUM(revenue) FROM sales GROUP BY product;
AGGREGATE AVG(sum_revenue) FROM sales;
FILTER sales WHERE avg_sum_revenue > 0;
VISUALIZE LINE OF avg_sum_revenue FROM sales;''')
    assert symbols.statement_schemas[id(program.statements[1])] == {"product": STRING, "sum_revenue": INTEGER}
    assert symbols.statement_schemas[id(program.statements[2])] == {"avg_sum_revenue": NUMERIC}
    assert list(symbols.lookup("sales").columns) == ["avg_sum_revenue"]


def test_invalid_statement_does_not_publish_schema():
    program = Parser(Lexer('LOAD "normal.csv" AS sales; AGGREGATE SUM(product) FROM sales;').tokenize()).parse()
    analyzer = SemanticAnalyzer(FIXTURES)
    with pytest.raises(SemanticAnalysisError):
        analyzer.analyze(program)
    assert list(analyzer.symbol_table.lookup("sales").columns) == ["id", "product", "revenue", "quantity"]
    assert not analyzer.symbol_table.statement_schemas


def test_driver_rejects_semantics_before_lowering_or_execution(monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid source reached a later stage")
    monkeypatch.setattr("src.main.IRGenerator.generate", forbidden)
    monkeypatch.setattr("src.main.ExecutionEngine.execute", forbidden)
    assert compile_source('LOAD "normal.csv" AS sales; AGGREGATE SUM(product) FROM sales;', FIXTURES) == 1
    output = capsys.readouterr().out
    assert "Semantic error at line 1, column" in output
    assert "SUM requires a numeric column" in output
