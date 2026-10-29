"""Literal sorting expectations from the Phase 3 fixtures, via the full compiler."""

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.executor import DataAnalysisModule, ExecutionEngine, ExecutionError, VisualizationModule
from src.interpreter.ir import IRGenerator
from src.lexer.lexer import Lexer
from src.main import compile_source, main
from src.parser.parser import Parser
from src.semantic.semantic import SemanticAnalyzer


FIXTURES = Path(__file__).parent / "fixtures" / "phase3"


def compile_ir(source, directory=FIXTURES):
    program = Parser(Lexer(source).tokenize()).parse()
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


@pytest.mark.parametrize("column,direction,ids", [
    ("revenue", "", [6, 5, 3, 2, 4, 1]),
    ("revenue", "ASC", [6, 5, 3, 2, 4, 1]),
    ("revenue", "DESC", [1, 4, 2, 3, 5, 6]),
    ("quantity", "ASC", [5, 2, 6, 1, 4, 3]),
    ("quantity", "DESC", [3, 1, 4, 2, 6, 5]),
])
def test_numeric_sort_order_and_full_row_preservation(column, direction, ids):
    engine = execute("normal.csv", f"SORT {column} {direction} FROM sales;")
    original, result = engine.tables["T1"], engine.result()
    assert list(result["id"]) == ids
    assert list(original["id"]) == [1, 2, 3, 4, 5, 6]
    pd.testing.assert_frame_equal(result, original.iloc[[identifier - 1 for identifier in ids]])
    assert engine.bindings["sales"] == engine.last_output == "T2"


@pytest.mark.parametrize("direction,ids", [
    ("ASC", [8, 7, 4, 1, 2, 3, 5, 6]),
    ("DESC", [1, 4, 7, 8, 2, 3, 5, 6]),
])
def test_missing_numeric_values_are_last_and_stable(direction, ids):
    result = execute("nulls.csv", f"SORT revenue {direction} FROM sales;").result()
    assert list(result["id"]) == ids
    assert list(result.loc[result["revenue"].isna(), "id"]) == [2, 3, 5, 6]


@pytest.mark.parametrize("direction,ids", [
    ("ASC", [2, 4, 6, 3, 1, 5]), ("DESC", [1, 3, 6, 2, 4, 5]),
])
def test_text_sort_is_case_sensitive_stable_and_nulls_last(direction, ids):
    result = execute("words.csv", f"SORT product {direction} FROM sales;").result()
    assert list(result["id"]) == ids


@pytest.mark.parametrize("direction,ids", [("ASC", [5, 2, 3, 4, 1]), ("DESC", [1, 4, 3, 2, 5])])
def test_text_uses_unicode_lexicographic_order(tmp_path, direction, ids):
    (tmp_path / "data.csv").write_text("id,word\n1,é\n2,Z\n3,a\n4,É\n5,A\n", encoding="utf-8")
    ir = compile_ir(f'LOAD "data.csv" AS sales; SORT word {direction} FROM sales;', tmp_path)
    engine = ExecutionEngine()
    engine.execute(ir)
    assert list(engine.result()["id"]) == ids


@pytest.mark.parametrize("direction,ids", [("ASC", [1, 2]), ("DESC", [2, 1])])
def test_mixed_csv_inferred_as_text_is_not_coerced(direction, ids):
    result = execute("mixed.csv", f"SORT revenue {direction} FROM sales;").result()
    assert list(result["id"]) == ids
    assert set(result["revenue"]) == {"10", "oops"}


def test_ties_follow_current_input_order_after_an_earlier_sort():
    result = execute("normal.csv", "SORT id DESC FROM sales; SORT quantity ASC FROM sales;").result()
    assert list(result["id"]) == [5, 6, 2, 4, 1, 3]


@pytest.mark.parametrize("filename,prefix", [("empty.csv", ""), ("normal.csv", "FILTER sales WHERE id > 100;")])
@pytest.mark.parametrize("direction", ["ASC", "DESC"])
def test_empty_input_preserves_schema_and_dtypes(filename, prefix, direction):
    engine = execute(filename, f"{prefix} SORT revenue {direction} FROM sales;")
    source = engine.tables["T1" if filename == "empty.csv" else "T2"]
    assert engine.result().empty
    pd.testing.assert_frame_equal(engine.result(), source)


@pytest.mark.parametrize("direction", ["ASC", "DESC"])
def test_all_null_sort_keys_retain_all_rows(direction):
    engine = execute("all_null.csv", f"SORT revenue {direction} FROM sales;")
    assert list(engine.result()["id"]) == [1, 2]
    pd.testing.assert_frame_equal(engine.result(), engine.tables["T1"])


@pytest.mark.parametrize("direction", ["ASC", "DESC"])
def test_singleton_sort(direction):
    result = execute("normal.csv", f"FILTER sales WHERE id == 1; SORT revenue {direction} FROM sales;").result()
    assert list(result["id"]) == [1]


@pytest.mark.parametrize("direction,rows", [
    ("ASC", [("C", -5), ("B", 17.5), ("A", 17.5)]),
    ("DESC", [("B", 17.5), ("A", 17.5), ("C", -5)]),
])
def test_sort_grouped_aggregate_preserves_ties_and_nullable_types(direction, rows):
    engine = execute("normal.csv", f"""AGGREGATE SUM(revenue) FROM sales GROUP BY product;
SORT sum_revenue {direction} FROM sales;""")
    assert_rows(engine.result(), ["product", "sum_revenue"], rows)
    assert engine.result().dtypes.equals(engine.tables["T2"].dtypes)


@pytest.mark.parametrize("direction,rows", [
    ("ASC", [("C", -5), (None, 5), ("B", 10), ("A", None)]),
    ("DESC", [("B", 10), (None, 5), ("C", -5), ("A", None)]),
])
def test_null_aggregate_results_sort_last(direction, rows):
    result = execute("nulls.csv", f"""AGGREGATE SUM(revenue) FROM sales GROUP BY product;
SORT sum_revenue {direction} FROM sales;""").result()
    assert_rows(result, ["product", "sum_revenue"], rows)
    assert str(result["sum_revenue"].dtype) == "Int64"


@pytest.mark.parametrize("direction,rows", [
    ("ASC", [("A", None), ("B", 10), ("C", -5), (None, 5)]),
    ("DESC", [("C", -5), ("B", 10), ("A", None), (None, 5)]),
])
def test_sort_grouping_column_puts_null_key_last(direction, rows):
    result = execute("nulls.csv", f"""AGGREGATE SUM(revenue) FROM sales GROUP BY product;
SORT product {direction} FROM sales;""").result()
    assert_rows(result, ["product", "sum_revenue"], rows)


@pytest.mark.parametrize("direction", ["ASC", "DESC"])
def test_empty_grouped_aggregate_sort_preserves_types(direction):
    engine = execute("normal.csv", f"""FILTER sales WHERE id > 100;
AGGREGATE SUM(revenue) FROM sales GROUP BY product;
SORT sum_revenue {direction} FROM sales;""")
    pd.testing.assert_frame_equal(engine.result(), engine.tables["T3"])
    assert engine.result().empty and str(engine.result()["sum_revenue"].dtype) == "Float64"


@pytest.mark.parametrize("direction", ["ASC", "DESC"])
def test_single_null_aggregate_result_sort(direction):
    result = execute("nulls.csv", f'''FILTER sales WHERE product == "A";
AGGREGATE SUM(revenue) FROM sales;
SORT sum_revenue {direction} FROM sales;''').result()
    assert_rows(result, ["sum_revenue"], [(None,)])


def test_full_select_filter_group_sort_workflow():
    result = execute("normal.csv", """SELECT product, revenue FROM sales;
FILTER sales WHERE revenue >= 5;
AGGREGATE SUM(revenue) FROM sales GROUP BY product;
SORT sum_revenue DESC FROM sales;""").result()
    assert_rows(result, ["product", "sum_revenue"], [("B", 17.5), ("A", 17.5)])


def test_filter_then_sort_aggregate_output():
    result = execute("normal.csv", """AGGREGATE SUM(revenue) FROM sales GROUP BY product;
FILTER sales WHERE sum_revenue > 0;
SORT product ASC FROM sales;""").result()
    assert_rows(result, ["product", "sum_revenue"], [("A", 17.5), ("B", 17.5)])


def test_sort_before_grouping_sets_group_encounter_order():
    result = execute("normal.csv", """SORT product ASC FROM sales;
AGGREGATE COUNT(quantity) FROM sales GROUP BY product;""").result()
    assert_rows(result, ["product", "count_quantity"], [("A", 2), ("B", 2), ("C", 2)])


def test_contextual_sort_asc_desc_names_execute():
    ir = compile_ir('''LOAD "contextual.csv" AS sort;
SELECT asc, desc FROM sort;
SORT desc DESC FROM sort;''')
    engine = ExecutionEngine()
    engine.execute(ir)
    assert_rows(engine.result(), ["asc", "desc"], [("low", 2), ("mid", 2), ("high", 1)])
    assert engine.bindings == {"sort": "T3"}


def test_sort_keeps_other_dataset_binding_and_feeds_projection():
    ir = compile_ir('''LOAD "normal.csv" AS sales;
LOAD "words.csv" AS other;
SORT revenue DESC FROM sales;
SORT product ASC FROM other;
SELECT product FROM sales;''')
    engine = ExecutionEngine()
    engine.execute(ir)
    assert engine.bindings == {"sales": "T5", "other": "T4"}
    assert list(engine.tables["T4"]["id"]) == [2, 4, 6, 3, 1, 5]
    assert list(engine.result()["product"]) == ["B", "A", "A", "B", "C", "C"]


@pytest.mark.parametrize("original,replacement,message", [
    ("revenue\n1\n2\n", "revenue\noops\n2\n", "numeric runtime column"),
    ("revenue\na\nb\n", "revenue\n10\n20\n", "String runtime column"),
    ("revenue\n1\n2\n", "other\n1\n2\n", "not in the current table"),
])
def test_runtime_schema_drift_does_not_publish_sort_result(tmp_path, original, replacement, message):
    path = tmp_path / "data.csv"
    path.write_text(original, encoding="utf-8")
    ir = compile_ir('LOAD "data.csv" AS sales; SORT revenue FROM sales;', tmp_path)
    path.write_text(replacement, encoding="utf-8")
    engine = ExecutionEngine()
    with pytest.raises(ExecutionError, match=rf"Instruction 2 \(SORT\).*{message}"):
        engine.execute(ir)
    assert set(engine.tables) == {"T1"}
    assert engine.last_output == engine.bindings["sales"] == "T1"


def test_mixed_runtime_values_are_rejected_without_coercion():
    class ChangedData(DataAnalysisModule):
        def load(self, path):
            return pd.DataFrame({"revenue": [1, "oops"]})
    ir = compile_ir('LOAD "normal.csv" AS sales; SORT revenue FROM sales;')
    with pytest.raises(ExecutionError, match="numeric runtime column"):
        ExecutionEngine(analysis=ChangedData()).execute(ir)


def test_runtime_sort_requires_checked_type_metadata():
    ir = compile_ir('LOAD "normal.csv" AS sales; SORT revenue FROM sales;')
    ir.instructions[-1].column_type = None
    with pytest.raises(ExecutionError, match="semantically validated column type"):
        ExecutionEngine().execute(ir)


def test_sorted_input_reaches_real_visualization():
    class RecordingVisualization(VisualizationModule):
        def plot(self, table, chart_type, column):
            self.figure = super().plot(table, chart_type, column)
            return self.figure
    visualization = RecordingVisualization(show=False)
    try:
        engine = execute("normal.csv", "SORT revenue ASC FROM sales; VISUALIZE LINE OF revenue FROM sales;", visualization)
        line = visualization.figure.axes[0].lines[0]
        assert list(line.get_xdata()) == [0, 1, 2, 3, 4, 5]
        assert list(line.get_ydata()) == [-5, 0, 5, 7.5, 10, 12.5]
        assert engine.last_output == engine.bindings["sales"] == "T2"
    finally:
        if hasattr(visualization, "figure"):
            plt.close(visualization.figure)


def test_driver_shows_sort_ast_ir_and_runs(capsys):
    assert compile_source('LOAD "normal.csv" AS sales; SORT revenue DESC FROM sales;', FIXTURES, dump_ast=True, dump_ir=True) == 0
    output = capsys.readouterr().out
    assert "SortStmt" in output and "SORT revenue DESC\n    T1 -> T2" in output
    assert "Result (T2, 6 row(s))" in output


def test_cli_sorts_aggregate_output(tmp_path, capsys):
    (tmp_path / "data.csv").write_text("product,revenue\nA,1\nB,2\nA,3\n", encoding="utf-8")
    path = tmp_path / "program.dl"
    path.write_text('LOAD "data.csv" AS sales; AGGREGATE SUM(revenue) FROM sales GROUP BY product; SORT sum_revenue DESC FROM sales;', encoding="utf-8")
    assert main([str(path), "--ir"]) == 0
    output = capsys.readouterr().out
    assert "SORT sum_revenue DESC" in output and "Result (T3, 2 row(s))" in output
