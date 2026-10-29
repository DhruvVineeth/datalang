"""Hand-calculated aggregation expectations exercised through every compiler stage."""

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.executor import ExecutionEngine, ExecutionError, VisualizationModule
from src.interpreter.ir import IRGenerator
from src.lexer.lexer import Lexer
from src.main import compile_source, main
from src.parser.parser import Parser
from src.semantic.semantic import SemanticAnalyzer


FIXTURES = Path(__file__).parent / "fixtures" / "phase3"
FUNCTIONS = ["SUM", "AVG", "COUNT", "MIN", "MAX"]


def compile_ir(source, directory=FIXTURES):
    tokens = Lexer(source).tokenize()
    program = Parser(tokens).parse()
    symbols = SemanticAnalyzer(directory).analyze(program)
    return IRGenerator(symbols).generate(program)


def execute(filename, fragment, visualization=None):
    ir = compile_ir(f'LOAD "{filename}" AS sales; ' + fragment)
    engine = ExecutionEngine(visualization=visualization)
    engine.execute(ir)
    return engine


def assert_rows(frame, columns, rows):
    assert list(frame.columns) == columns
    actual = [tuple(None if pd.isna(value) else value for value in row)
              for row in frame.itertuples(index=False, name=None)]
    assert actual == rows


@pytest.mark.parametrize("function,revenue,quantity", [
    ("SUM", 30, 9), ("AVG", 5, 1.5), ("COUNT", 6, 6),
    ("MIN", -5, 0), ("MAX", 12.5, 3),
])
@pytest.mark.parametrize("column", ["revenue", "quantity"])
def test_normal_ungrouped(function, revenue, quantity, column):
    result = execute("normal.csv", f"AGGREGATE {function}({column}) FROM sales;").result()
    name = f"{function.lower()}_{column}"
    assert_rows(result, [name], [(revenue if column == "revenue" else quantity,)])
    expected_dtype = "Int64" if function == "COUNT" or column == "quantity" and function != "AVG" else "Float64"
    assert str(result[name].dtype) == expected_dtype


@pytest.mark.parametrize("function,values", [
    ("SUM", [17.5, 17.5, -5]), ("AVG", [8.75, 8.75, -2.5]),
    ("COUNT", [2, 2, 2]), ("MIN", [5, 7.5, -5]), ("MAX", [12.5, 10, 0]),
])
def test_normal_grouped_in_first_appearance_order(function, values):
    result = execute("normal.csv", f"AGGREGATE {function}(revenue) FROM sales GROUP BY product;").result()
    assert_rows(result, ["product", f"{function.lower()}_revenue"], list(zip(["B", "A", "C"], values)))


@pytest.mark.parametrize("function,value", [("SUM", 10), ("AVG", 2.5), ("COUNT", 4), ("MIN", -5), ("MAX", 10)])
def test_null_targets_are_skipped(function, value):
    result = execute("nulls.csv", f"AGGREGATE {function}(revenue) FROM sales;").result()
    assert_rows(result, [f"{function.lower()}_revenue"], [(value,)])


@pytest.mark.parametrize("function,values", [
    ("SUM", [10, None, 5, -5]), ("AVG", [10, None, 5, -2.5]),
    ("COUNT", [1, 0, 1, 2]), ("MIN", [10, None, 5, -5]), ("MAX", [10, None, 5, 0]),
])
def test_null_key_and_all_null_group(function, values):
    result = execute("nulls.csv", f"AGGREGATE {function}(revenue) FROM sales GROUP BY product;").result()
    name = f"{function.lower()}_revenue"
    assert_rows(result, ["product", name], list(zip(["B", "A", None, "C"], values)))
    assert str(result[name].dtype) == ("Float64" if function == "AVG" else "Int64")


def test_count_string_grouping_column_counts_values_not_rows():
    result = execute("nulls.csv", "AGGREGATE COUNT(product) FROM sales GROUP BY product;").result()
    assert_rows(result, ["product", "count_product"], [("B", 2), ("A", 2), (None, 0), ("C", 2)])
    result = execute("nulls.csv", "AGGREGATE COUNT(product) FROM sales;").result()
    assert_rows(result, ["count_product"], [(6,)])


@pytest.mark.parametrize("function", FUNCTIONS)
@pytest.mark.parametrize("grouped", [False, True])
def test_known_numeric_zero_rows(function, grouped):
    grouping = " GROUP BY product" if grouped else ""
    result = execute("normal.csv", f"FILTER sales WHERE id > 100; AGGREGATE {function}(revenue) FROM sales{grouping};").result()
    name = f"{function.lower()}_revenue"
    assert_rows(result, ["product", name] if grouped else [name], [] if grouped else [(0 if function == "COUNT" else None,)])
    assert str(result[name].dtype) == ("Int64" if function == "COUNT" else "Float64")


@pytest.mark.parametrize("function", FUNCTIONS)
@pytest.mark.parametrize("grouped", [False, True])
def test_known_numeric_all_null_rows(function, grouped):
    grouping = " GROUP BY product" if grouped else ""
    result = execute("nulls.csv", f'FILTER sales WHERE product == "A"; AGGREGATE {function}(revenue) FROM sales{grouping};').result()
    name = f"{function.lower()}_revenue"
    value = 0 if function == "COUNT" else None
    assert_rows(result, ["product", name] if grouped else [name], [("A", value)] if grouped else [(value,)])
    assert str(result[name].dtype) == ("Float64" if function == "AVG" else "Int64")


@pytest.mark.parametrize("function", FUNCTIONS)
@pytest.mark.parametrize("grouped", [False, True])
def test_singleton(function, grouped):
    grouping = " GROUP BY product" if grouped else ""
    result = execute("normal.csv", f"FILTER sales WHERE id == 1; AGGREGATE {function}(revenue) FROM sales{grouping};").result()
    name = f"{function.lower()}_revenue"
    value = 1 if function == "COUNT" else 12.5
    assert_rows(result, ["product", name] if grouped else [name], [("B", value)] if grouped else [(value,)])


@pytest.mark.parametrize("filename,grouped,rows", [
    ("empty.csv", False, [(0,)]), ("empty.csv", True, []),
    ("all_null.csv", False, [(0,)]), ("all_null.csv", True, [("A", 0), ("B", 0)]),
    ("mixed.csv", False, [(2,)]),
])
def test_count_loaded_empty_all_null_and_mixed_columns(filename, grouped, rows):
    grouping = " GROUP BY product" if grouped else ""
    result = execute(filename, f"AGGREGATE COUNT(revenue) FROM sales{grouping};").result()
    assert_rows(result, ["product", "count_revenue"] if grouped else ["count_revenue"], rows)
    assert str(result["count_revenue"].dtype) == "Int64"


def test_numeric_nullable_grouping_key_retains_its_type(tmp_path):
    (tmp_path / "data.csv").write_text("id,key,value\n1,2,4\n2,,6\n3,1,\n4,2,8\n5,,1\n", encoding="utf-8")
    ir = compile_ir('LOAD "data.csv" AS sales; AGGREGATE SUM(value) FROM sales GROUP BY key;', tmp_path)
    engine = ExecutionEngine()
    engine.execute(ir)
    result = engine.result()
    assert_rows(result, ["key", "sum_value"], [(2, 12), (None, 7), (1, None)])
    assert str(result["key"].dtype) == str(result["sum_value"].dtype) == "Int64"


def test_select_filter_aggregate_and_filter_select_result():
    engine = execute("normal.csv", """SELECT product, revenue FROM sales;
FILTER sales WHERE revenue >= 5;
AGGREGATE SUM(revenue) FROM sales GROUP BY product;
FILTER sales WHERE sum_revenue > 0;
SELECT sum_revenue FROM sales;""")
    assert_rows(engine.result(), ["sum_revenue"], [(17.5,), (17.5,)])
    assert_rows(engine.tables["T4"], ["product", "sum_revenue"], [("B", 17.5), ("A", 17.5)])
    assert engine.bindings["sales"] == engine.last_output == "T6"
    assert len(engine.tables["T1"]) == 6
    assert list(engine.tables["T1"].columns) == ["id", "product", "revenue", "quantity"]


def test_aggregate_of_aggregate_uses_group_totals():
    result = execute("normal.csv", """AGGREGATE SUM(revenue) FROM sales GROUP BY product;
AGGREGATE AVG(sum_revenue) FROM sales;""").result()
    assert_rows(result, ["avg_sum_revenue"], [(10,)])


def test_filter_after_aggregation_removes_negative_group():
    result = execute("normal.csv", """AGGREGATE SUM(revenue) FROM sales GROUP BY product;
FILTER sales WHERE sum_revenue > 0;""").result()
    assert_rows(result, ["product", "sum_revenue"], [("B", 17.5), ("A", 17.5)])


@pytest.mark.parametrize("function,column,value", [("SUM", "value", 9), ("COUNT", "value", 2), ("COUNT", "key", 0)])
def test_entirely_null_grouping_key_forms_one_group(tmp_path, function, column, value):
    (tmp_path / "data.csv").write_text("key,value\n,4\n,5\n", encoding="utf-8")
    ir = compile_ir(f'LOAD "data.csv" AS sales; AGGREGATE {function}({column}) FROM sales GROUP BY key;', tmp_path)
    engine = ExecutionEngine()
    engine.execute(ir)
    assert_rows(engine.result(), ["key", f"{function.lower()}_{column}"], [(None, value)])


def test_independent_dataset_bindings():
    ir = compile_ir('''LOAD "normal.csv" AS sales;
LOAD "nulls.csv" AS other;
AGGREGATE SUM(revenue) FROM sales GROUP BY product;
AGGREGATE COUNT(revenue) FROM other;
SELECT sum_revenue FROM sales;''')
    engine = ExecutionEngine()
    engine.execute(ir)
    assert_rows(engine.tables["T4"], ["count_revenue"], [(4,)])
    assert_rows(engine.result(), ["sum_revenue"], [(17.5,), (17.5,), (-5,)])
    assert engine.bindings == {"sales": "T5", "other": "T4"}


def test_output_name_preserves_column_case(tmp_path):
    (tmp_path / "data.csv").write_text("Revenue\n1.5\n2.5\n", encoding="utf-8")
    ir = compile_ir('LOAD "data.csv" AS sales; AGGREGATE SUM(Revenue) FROM sales; SELECT sum_Revenue FROM sales;', tmp_path)
    engine = ExecutionEngine()
    engine.execute(ir)
    assert_rows(engine.result(), ["sum_Revenue"], [(4,)])


def test_grouped_result_reaches_real_visualization():
    class RecordingVisualization(VisualizationModule):
        def plot(self, table, chart_type, column):
            self.figure = super().plot(table, chart_type, column)
            return self.figure
    visualization = RecordingVisualization(show=False)
    try:
        engine = execute("normal.csv", """AGGREGATE SUM(revenue) FROM sales GROUP BY product;
VISUALIZE LINE OF sum_revenue FROM sales;""", visualization)
        line = visualization.figure.axes[0].lines[0]
        assert list(line.get_xdata()) == [0, 1, 2]
        assert list(line.get_ydata()) == [17.5, 17.5, -5]
        assert engine.last_output == engine.bindings["sales"] == "T2"
    finally:
        if hasattr(visualization, "figure"):
            plt.close(visualization.figure)


def test_schema_drift_has_runtime_context_and_no_result_publication(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text("product,revenue\nA,10\nB,20\n", encoding="utf-8")
    ir = compile_ir('LOAD "data.csv" AS sales; AGGREGATE SUM(revenue) FROM sales;', tmp_path)
    path.write_text("product,revenue\nA,oops\nB,20\n", encoding="utf-8")
    engine = ExecutionEngine()
    with pytest.raises(ExecutionError, match=r"Instruction 2 \(AGGREGATE\).*numeric runtime column"):
        engine.execute(ir)
    assert set(engine.tables) == {"T1"}
    assert engine.last_output == engine.bindings["sales"] == "T1"


def test_runtime_defends_against_invalid_ir_function():
    ir = compile_ir('LOAD "normal.csv" AS sales; AGGREGATE SUM(revenue) FROM sales;')
    ir.instructions[-1].func = "MEDIAN"
    with pytest.raises(ExecutionError, match="Unsupported aggregate function"):
        ExecutionEngine().execute(ir)


def test_runtime_requires_checked_schema_metadata():
    ir = compile_ir('LOAD "normal.csv" AS sales; AGGREGATE SUM(revenue) FROM sales;')
    ir.instructions[-1].output_schema = None
    with pytest.raises(ExecutionError, match="semantically validated output schema"):
        ExecutionEngine().execute(ir)


def test_driver_executes_aggregate_and_reports_ir(capsys):
    source = 'LOAD "normal.csv" AS sales; AGGREGATE SUM(revenue) FROM sales GROUP BY product;'
    assert compile_source(source, FIXTURES, dump_ast=True, dump_ir=True) == 0
    output = capsys.readouterr().out
    assert "AggregateStmt" in output and "AGGREGATE SUM(revenue) GROUP BY product" in output
    assert "Result (T2, 3 row(s))" in output and "sum_revenue" in output


def test_cli_runs_relative_fixture_path(tmp_path, capsys):
    (tmp_path / "data.csv").write_text("revenue\n2\n3\n", encoding="utf-8")
    path = tmp_path / "program.dl"
    path.write_text('LOAD "data.csv" AS sales; AGGREGATE SUM(revenue) FROM sales;', encoding="utf-8")
    assert main([str(path), "--ir"]) == 0
    output = capsys.readouterr().out
    assert "sum_revenue" in output and "Result (T2, 1 row(s))" in output
