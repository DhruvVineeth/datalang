"""
Tests for the DataLang symbol table and semantic analyzer.

Covers CSV schema inspection after LOAD and validation of SELECT, FILTER,
and PLOT (PlotStmt / VISUALIZE) against the architecture proposal.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.lexer.lexer import Lexer
from src.parser.parser import Parser
from src.semantic.semantic import SemanticAnalysisError, SemanticAnalyzer
from src.symbol_table.symbol_table import INTEGER, NUMERIC, STRING, infer_column_type


REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = REPO_ROOT / "examples"


def parse(source: str):
    return Parser(Lexer(source).tokenize()).parse()


def analyze(source: str, source_dir: Path):
    return SemanticAnalyzer(source_dir=source_dir).analyze(parse(source))


def analyze_expecting_errors(source: str, source_dir: Path):
    try:
        SemanticAnalyzer(source_dir=source_dir).analyze(parse(source))
    except SemanticAnalysisError as exc:
        return [error.message for error in exc.errors]
    raise AssertionError("Expected semantic errors, but analysis succeeded")


def test_type_inference():
    assert infer_column_type(["10", "5", "12"]) == INTEGER
    assert infer_column_type(["1500.50", "800", "2200.00"]) == NUMERIC
    assert infer_column_type(["Widget", "Gadget"]) == STRING
    print("PASSED type inference")


def test_load_inspects_csv_schema():
    source = 'LOAD "sales.csv" AS sales;'
    table = analyze(source, EXAMPLES)
    assert table.has_dataset("sales")
    assert table.lookup_column("sales", "product").data_type == STRING
    assert table.lookup_column("sales", "revenue").data_type == NUMERIC
    assert table.lookup_column("sales", "quantity").data_type == INTEGER
    print("PASSED LOAD inspects CSV schema")


def test_valid_select_filter_plot():
    source = """
LOAD "sales.csv" AS sales;
SELECT product, revenue FROM sales;
FILTER sales WHERE revenue > 1000;
VISUALIZE BAR OF product FROM sales;
"""
    table = analyze(source, EXAMPLES)
    assert table.column_exists("sales", "product")
    print("PASSED valid SELECT, FILTER, and PLOT")


def test_nonexistent_column():
    source = """
LOAD "sales.csv" AS sales;
SELECT salary FROM sales;
"""
    messages = analyze_expecting_errors(source, EXAMPLES)
    assert any("salary" in message and "does not exist" in message for message in messages)
    print("PASSED nonexistent column")


def test_incompatible_types():
    source = """
LOAD "sales.csv" AS sales;
FILTER sales WHERE product > 1000;
"""
    messages = analyze_expecting_errors(source, EXAMPLES)
    assert any("not applicable" in message for message in messages)
    print("PASSED incompatible FILTER types")


def test_filter_string_vs_number():
    source = """
LOAD "sales.csv" AS sales;
FILTER sales WHERE revenue == "North";
"""
    messages = analyze_expecting_errors(source, EXAMPLES)
    assert any("Incompatible types" in message for message in messages)
    print("PASSED FILTER string compared to numeric column")


def test_unloaded_dataset():
    source = "SELECT product FROM sales;"
    messages = analyze_expecting_errors(source, EXAMPLES)
    assert any("has not been loaded" in message for message in messages)
    print("PASSED operation on unloaded dataset")


def test_invalid_visualization_column_missing():
    source = """
LOAD "sales.csv" AS sales;
VISUALIZE BAR OF salary FROM sales;
"""
    messages = analyze_expecting_errors(source, EXAMPLES)
    assert any("Invalid visualization column" in message for message in messages)
    print("PASSED missing visualization column")


def test_invalid_visualization_column_type():
    source = """
LOAD "sales.csv" AS sales;
VISUALIZE LINE OF product FROM sales;
"""
    messages = analyze_expecting_errors(source, EXAMPLES)
    assert any("LINE" in message and "numeric" in message for message in messages)
    print("PASSED invalid visualization column type")


def test_missing_csv_file():
    source = 'LOAD "does-not-exist.csv" AS sales;'
    with tempfile.TemporaryDirectory() as tmp:
        messages = analyze_expecting_errors(source, Path(tmp))
    assert any("not found" in message for message in messages)
    print("PASSED missing CSV on LOAD")


def test_compound_filter_checks_each_column():
    source = """
LOAD "sales.csv" AS sales;
FILTER sales WHERE product == "Widget" AND missing > 1;
"""
    messages = analyze_expecting_errors(source, EXAMPLES)
    assert any("missing" in message for message in messages)
    print("PASSED compound FILTER reports missing column")


def run_all_tests():
    print("=" * 70)
    print("DATALANG SYMBOL TABLE / SEMANTIC ANALYZER TESTS")
    print("=" * 70)
    print()
    test_type_inference()
    test_load_inspects_csv_schema()
    test_valid_select_filter_plot()
    test_nonexistent_column()
    test_incompatible_types()
    test_filter_string_vs_number()
    test_unloaded_dataset()
    test_invalid_visualization_column_missing()
    test_invalid_visualization_column_type()
    test_missing_csv_file()
    test_compound_filter_checks_each_column()
    print()
    print("=" * 70)
    print("ALL TESTS PASSED")
    print("=" * 70)


if __name__ == "__main__":
    run_all_tests()
