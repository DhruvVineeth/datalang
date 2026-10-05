"""
Tests for DataLang IR generation and Pandas execution of LOAD, SELECT, FILTER.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.executor import ExecutionEngine, VisualizationModule
from src.interpreter.ir import FilterIR, IRGenerator, LoadIR, PlotIR, SelectIR
from src.lexer.lexer import Lexer
from src.parser.parser import Parser
from src.semantic.semantic import SemanticAnalyzer


REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = REPO_ROOT / "examples"


def compile_ir(source: str, source_dir: Path = EXAMPLES):
    program = Parser(Lexer(source).tokenize()).parse()
    symbols = SemanticAnalyzer(source_dir=source_dir).analyze(program)
    ir = IRGenerator(symbols).generate(program)
    return ir, symbols


def test_lower_load_select_filter_temps():
    source = """
LOAD "sales.csv" AS sales;
SELECT product, revenue FROM sales;
FILTER sales WHERE revenue > 1000;
"""
    ir, _ = compile_ir(source)
    assert len(ir.instructions) == 3
    load, select, filt = ir.instructions
    assert isinstance(load, LoadIR)
    assert load.output == "T1"
    assert load.name == "sales"
    assert isinstance(select, SelectIR)
    assert select.input == "T1" and select.output == "T2"
    assert select.columns == ["product", "revenue"]
    assert isinstance(filt, FilterIR)
    assert filt.input == "T2" and filt.output == "T3"
    print("PASSED IR lowering uses sequential temps T1 -> T2 -> T3")


def test_execute_load_select_filter():
    source = """
LOAD "sales.csv" AS sales;
SELECT product, revenue FROM sales;
FILTER sales WHERE revenue > 1000;
"""
    ir, _ = compile_ir(source)
    engine = ExecutionEngine()
    tables = engine.execute(ir)

    assert set(tables) == {"T1", "T2", "T3"}
    assert list(tables["T1"].columns) == ["product", "revenue", "quantity"]
    assert list(tables["T2"].columns) == ["product", "revenue"]
    assert len(tables["T1"]) == 3

    result = engine.result()
    assert result is not None
    assert list(result.columns) == ["product", "revenue"]
    assert set(result["product"]) == {"Widget", "Gizmo"}
    assert all(result["revenue"] > 1000)
    print("PASSED Pandas execution of LOAD, SELECT, FILTER")


def test_compound_filter():
    source = """
LOAD "sales.csv" AS sales;
FILTER sales WHERE product == "Widget" OR quantity >= 12;
"""
    ir, _ = compile_ir(source)
    engine = ExecutionEngine()
    engine.execute(ir)
    result = engine.result()
    assert result is not None
    assert set(result["product"]) == {"Widget", "Gizmo"}
    print("PASSED compound FILTER AND/OR on runtime table")


def test_plot_is_lowered_but_does_not_block_execution():
    source = """
LOAD "sales.csv" AS sales;
SELECT product, revenue FROM sales;
FILTER sales WHERE revenue > 1000;
VISUALIZE BAR OF product FROM sales;
"""
    ir, _ = compile_ir(source)
    assert isinstance(ir.instructions[-1], PlotIR)
    class RecordingVisualization(VisualizationModule):
        def plot(self, table, chart_type, column):
            self.table = table
            self.chart_type = chart_type
            self.column = column

    visualization = RecordingVisualization(show=False)
    engine = ExecutionEngine(visualization=visualization)
    engine.execute(ir)
    result = engine.result()
    assert result is not None
    assert engine.last_output == "T3"
    assert visualization.table is result
    assert visualization.chart_type == "BAR" and visualization.column == "product"
    print("PASSED PLOT executes on the filtered table and retains the result")


def test_filter_only_keeps_matching_rows():
    source = """
LOAD "sales.csv" AS sales;
FILTER sales WHERE revenue > 2000;
"""
    ir, _ = compile_ir(source)
    engine = ExecutionEngine()
    engine.execute(ir)
    result = engine.result()
    assert result is not None
    assert list(result["product"]) == ["Gizmo"]
    print("PASSED FILTER-only program")


def run_all_tests():
    print("=" * 70)
    print("DATALANG IR / EXECUTION TESTS")
    print("=" * 70)
    print()
    test_lower_load_select_filter_temps()
    test_execute_load_select_filter()
    test_compound_filter()
    test_plot_is_lowered_but_does_not_block_execution()
    test_filter_only_keeps_matching_rows()
    print()
    print("=" * 70)
    print("ALL TESTS PASSED")
    print("=" * 70)


if __name__ == "__main__":
    run_all_tests()
