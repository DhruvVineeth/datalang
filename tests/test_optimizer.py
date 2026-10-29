"""Guarded double-NOT equivalence through the validated compiler pipeline."""

import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.executor import DataAnalysisModule, ExecutionEngine, ExecutionError, eval_predicate
from src import executor
from src.interpreter.ir import BoolPred, ComparePred, FilterIR, IRGenerator, IRProgram, NotPred
from src.interpreter.optimizer import optimize_ir
from src.lexer.lexer import Lexer
from src.main import compile_source
from src.parser.parser import Parser
from src.semantic.semantic import SemanticAnalyzer


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures" / "phase3"


def compile_ir(source, directory=FIXTURES):
    ast = Parser(Lexer(source).tokenize()).parse()
    symbols = SemanticAnalyzer(directory).analyze(ast)
    return IRGenerator(symbols).generate(ast)


def assert_state_equal(left, right):
    assert list(left.tables) == list(right.tables)
    assert left.bindings == right.bindings
    assert left.last_output == right.last_output
    for name in left.tables:
        pd.testing.assert_frame_equal(left.tables[name], right.tables[name])


@pytest.mark.parametrize("filename,fragment,ids", [
    ("normal.csv", "NOT NOT revenue > 7", [1, 2, 4]),
    ("normal.csv", 'NOT NOT product == "A"', [2, 4]),
    ("nulls.csv", "NOT NOT revenue > 0", [1, 4]),
    ("nulls.csv", "NOT NOT revenue != 0", [1, 2, 3, 4, 5, 6, 8]),
    ("empty.csv", 'NOT NOT product == "A"', []),
    ("all_null.csv", 'NOT NOT revenue == "A"', []),
    ("normal.csv", "NOT NOT NOT revenue > 7", [3, 5, 6]),
    ("normal.csv", "NOT NOT NOT NOT revenue > 7", [1, 2, 4]),
    ("normal.csv", 'NOT NOT revenue > 7 AND NOT NOT product != "B"', [2, 4]),
    ("normal.csv", 'NOT NOT revenue > 7 OR NOT NOT product == "C"', [1, 2, 4, 5, 6]),
])
def test_fixture_results_and_every_intermediate_table(filename, fragment, ids):
    source = f'LOAD "{filename}" AS sales; FILTER sales WHERE {fragment};'
    raw = compile_ir(source)
    off, on = ExecutionEngine(), ExecutionEngine()
    off.execute(raw)
    on.execute(optimize_ir(raw))
    assert list(on.result()["id"]) == ids
    assert_state_equal(off, on)


def test_pipeline_named_datasets_nullable_aggregation_and_plot_order():
    raw = compile_ir('''LOAD "nulls.csv" AS sales;
LOAD "normal.csv" AS other;
SELECT product, revenue FROM sales;
FILTER sales WHERE NOT NOT revenue != 0;
AGGREGATE SUM(revenue) FROM sales GROUP BY product;
FILTER sales WHERE NOT NOT sum_revenue >= 0;
SORT sum_revenue DESC FROM sales;
VISUALIZE BAR OF product FROM sales;
FILTER other WHERE NOT NOT revenue > 7;
VISUALIZE LINE OF revenue FROM other;''')

    class Plots:
        def __init__(self):
            self.calls = []

        def plot(self, table, chart_type, column):
            self.calls.append((table.copy(), chart_type, column))

    off_plots, on_plots = Plots(), Plots()
    off, on = ExecutionEngine(visualization=off_plots), ExecutionEngine(visualization=on_plots)
    off.execute(raw)
    on.execute(optimize_ir(raw))
    assert_state_equal(off, on)
    assert len(on_plots.calls) == len(off_plots.calls) == 2
    for (left, *left_args), (right, *right_args) in zip(off_plots.calls, on_plots.calls):
        assert left_args == right_args
        pd.testing.assert_frame_equal(left, right)
    assert list(on.tables[on.bindings["sales"]]["sum_revenue"]) == [10, 5]
    assert list(on.result()["id"]) == [1, 2, 4]


def test_pass_preserves_source_ir_and_locations_and_is_idempotent():
    raw = compile_ir('LOAD "normal.csv" AS sales;\nFILTER sales WHERE NOT NOT revenue > 7;')
    optimized = optimize_ir(raw)
    old, new = raw.instructions[1], optimized.instructions[1]
    assert new is not old
    assert not old.condition.elide_double_not
    assert new.condition.elide_double_not
    assert optimized.format() == raw.format() == optimize_ir(optimized).format()
    assert optimized == raw
    for left, right in zip(raw.instructions, optimized.instructions):
        assert (left.source_line, left.source_column, left.output) == (
            right.source_line, right.source_column, right.output,
        )
    left, right = old.condition, new.condition
    while True:
        assert (left.source_line, left.source_column) == (right.source_line, right.source_column)
        if not isinstance(left, NotPred):
            assert left == right
            break
        left, right = left.operand, right.operand
    assert optimize_ir(raw, enabled=False) is raw


@pytest.mark.parametrize("operator", ["==", "!=", "<", ">", "<=", ">="])
@pytest.mark.parametrize("dtype", ["bool", "boolean"])
def test_boolean_masks_keep_nulls_index_name_and_attrs(monkeypatch, operator, dtype):
    raw = compile_ir(f'LOAD "normal.csv" AS sales; FILTER sales WHERE NOT NOT revenue {operator} 7;')
    mask = pd.Series([True, False] if dtype == "bool" else [True, False, pd.NA], dtype=dtype)
    mask.index = pd.Index([9] * len(mask), name="row")
    mask.name, mask.attrs = "predicate", {"origin": "test"}
    calls = []
    op = raw.instructions[1].condition.operand.operand.op

    def compare(*args):
        calls.append(op)
        return mask.copy()

    monkeypatch.setitem(executor._COMPARE, op, compare)
    table = pd.DataFrame({"revenue": [1]})
    off = eval_predicate(table, raw.instructions[1].condition)
    on = eval_predicate(table, optimize_ir(raw).instructions[1].condition)
    pd.testing.assert_series_equal(off, on)
    assert off.attrs == on.attrs == mask.attrs
    assert calls == [op, op]  # once in each mode, without short-circuiting


@pytest.mark.parametrize("runtime_csv,condition,expected", [
    ("id,product,quantity\n1,A,2\n", "NOT NOT revenue > 7", "FILTER column 'revenue'"),
    ("id,product,revenue,quantity\n1,A,oops,2\n", "NOT NOT revenue > 7", "Cannot compare column 'revenue'"),
    ("id,product,quantity\n1,A,2\n", "id > 100 AND NOT NOT revenue > 7", "FILTER column 'revenue'"),
    ("id,product,quantity\n1,A,2\n", "id > 0 OR NOT NOT revenue > 7", "FILTER column 'revenue'"),
])
def test_runtime_schema_drift_preserves_first_error_location_and_partial_state(tmp_path, runtime_csv, condition, expected):
    path = tmp_path / "data.csv"
    path.write_text("id,product,revenue,quantity\n1,A,10,2\n", encoding="utf-8")
    raw = compile_ir(f'''LOAD "data.csv" AS sales;
FILTER sales WHERE
  {condition};
SORT id FROM sales;
VISUALIZE BAR OF product FROM sales;''', tmp_path)
    path.write_text(runtime_csv, encoding="utf-8")

    class NoPlots:
        def plot(self, *args):
            pytest.fail("Execution continued after a failed FILTER")

    engines, errors = [], []
    for ir in (raw, optimize_ir(raw)):
        engine = ExecutionEngine(visualization=NoPlots())
        with pytest.raises(ExecutionError) as failure:
            engine.execute(ir)
        engines.append(engine)
        errors.append((str(failure.value), failure.value.line, failure.value.column))
    assert errors[0] == errors[1]
    assert expected in errors[0][0]
    assert "Instruction 2 (FILTER)" in errors[0][0]
    assert errors[0][1] == 3
    assert list(engines[0].tables) == ["T1"]
    assert_state_equal(*engines)


def test_inversions_are_skipped_only_when_enabled(monkeypatch):
    raw = compile_ir('LOAD "normal.csv" AS sales; FILTER sales WHERE NOT NOT revenue > 7;')
    ir = optimize_ir(raw)
    original, calls = pd.Series.__invert__, []

    def invert(values):
        calls.append(values.dtype)
        return original(values)

    monkeypatch.setattr(pd.Series, "__invert__", invert)
    on = ExecutionEngine()
    on.execute(ir)
    assert calls == []
    off = ExecutionEngine(optimize=False)
    off.execute(ir)
    assert len(calls) == 2
    assert_state_equal(off, on)


@pytest.mark.parametrize("values", [pd.Series([1, 0]), pd.Series([True, False], dtype=object), pd.Series(["bad"])])
def test_nonboolean_masks_use_original_inversions_and_errors(monkeypatch, values):
    raw = compile_ir('LOAD "normal.csv" AS sales; FILTER sales WHERE NOT NOT revenue > 7;')
    monkeypatch.setitem(executor._COMPARE, "GT", lambda *args: values)
    table = pd.DataFrame({"revenue": [1]})
    outcomes = []
    for ir in (raw, optimize_ir(raw)):
        try:
            outcomes.append(eval_predicate(table, ir.instructions[1].condition))
        except ExecutionError as exc:
            outcomes.append((str(exc), exc.line, exc.column))
    if isinstance(outcomes[0], pd.Series):
        pd.testing.assert_series_equal(*outcomes)
    else:
        assert outcomes[0] == outcomes[1]


def test_custom_analysis_backend_receives_original_mask_path(monkeypatch):
    raw = compile_ir('LOAD "normal.csv" AS sales; FILTER sales WHERE NOT NOT revenue > 7;')

    class Backend(DataAnalysisModule):
        pass

    original, calls = pd.Series.__invert__, []

    def invert(values):
        calls.append(1)
        return original(values)

    monkeypatch.setattr(pd.Series, "__invert__", invert)
    ExecutionEngine(analysis=Backend()).execute(optimize_ir(raw))
    assert len(calls) == 2


def test_dataframe_subclass_receives_original_mask_path(monkeypatch):
    raw = compile_ir('LOAD "normal.csv" AS sales; FILTER sales WHERE NOT NOT revenue > 7;')

    class Frame(pd.DataFrame):
        pass

    monkeypatch.setattr(DataAnalysisModule, "load", lambda *args: Frame({"revenue": [10, 5]}))
    original, calls = pd.Series.__invert__, []

    def invert(values):
        calls.append(1)
        return original(values)

    monkeypatch.setattr(pd.Series, "__invert__", invert)
    engine = ExecutionEngine()
    engine.execute(optimize_ir(raw))
    assert len(calls) == 2
    assert list(engine.result()["revenue"]) == [10]


def test_shared_and_cyclic_predicate_graphs_are_left_alone():
    leaf = ComparePred("x", "GT", 0)
    shared = BoolPred("AND", NotPred(NotPred(leaf)), leaf)
    cyclic = NotPred(NotPred(leaf))
    cyclic.operand.operand = cyclic
    for condition in (shared, cyclic):
        instruction = FilterIR("T1", condition, "T2")
        assert optimize_ir(IRProgram([instruction])).instructions[0] is instruction


@pytest.mark.parametrize("condition", [
    ComparePred("x", "GT", 0),
    NotPred(ComparePred("x", "GT", 0)),
    NotPred(NotPred(ComparePred("x", "UNKNOWN", 0))),
    NotPred(NotPred(BoolPred("XOR", ComparePred("x", "GT", 0), ComparePred("x", "LT", 2)))),
    NotPred(NotPred(object())),
])
def test_ineligible_predicates_are_untouched(condition):
    instruction = FilterIR("T1", condition, "T2")
    assert optimize_ir(IRProgram([instruction])).instructions[0] is instruction


def test_missing_operand_location_still_uses_inner_not_location():
    condition = NotPred(NotPred(ComparePred("missing", "GT", 0), source_line=5, source_column=8),
                        source_line=4, source_column=2)
    raw = IRProgram([FilterIR("T1", condition, "T2")])
    errors = []
    for ir in (raw, optimize_ir(raw)):
        with pytest.raises(ExecutionError) as failure:
            eval_predicate(pd.DataFrame(), ir.instructions[0].condition)
        errors.append((str(failure.value), failure.value.line, failure.value.column))
    assert errors[0] == errors[1]
    assert errors[0][1:] == (5, 8)


@pytest.mark.parametrize("fragment,stage", [("@", "Lexical"), ("FILTER sales WHERE NOT NOT;", "Syntax"),
                                           ("FILTER sales WHERE NOT NOT absent > 1;", "Semantic")])
@pytest.mark.parametrize("enabled", [False, True])
def test_validation_still_prevents_optimizer_and_execution(monkeypatch, capsys, fragment, stage, enabled):
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid source reached optimization or execution")

    monkeypatch.setattr("src.main.optimize_ir", forbidden)
    monkeypatch.setattr("src.main.ExecutionEngine", forbidden)
    assert compile_source('LOAD "normal.csv" AS sales; ' + fragment, FIXTURES, optimize=enabled) == 1
    assert stage + " error" in capsys.readouterr().out


@pytest.mark.parametrize("extra_flags", [[], ["--ast", "--ir"], ["--ir", "--no-execute"]])
@pytest.mark.parametrize("fragment,expected_status", [
    ("FILTER sales WHERE NOT NOT revenue > 7;", 0),
    ("FILTER sales WHERE NOT NOT absent > 7;", 1),
    ("FILTER sales WHERE NOT NOT;", 1),
    ("FILTER sales WHERE NOT NOT revenue > 999; VISUALIZE BAR OF product FROM sales;", 1),
])
def test_actual_cli_off_flag_preserves_stdout_stderr_and_exit(tmp_path, extra_flags, fragment, expected_status):
    csv_path = (FIXTURES / "normal.csv").as_posix()
    source = tmp_path / "program.dl"
    source.write_text(f'LOAD "{csv_path}" AS sales; {fragment}', encoding="utf-8")
    command = [sys.executable, "-B", "-m", "src.main", str(source), *extra_flags]
    on = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    off = subprocess.run([*command, "--no-optimize"], cwd=ROOT, capture_output=True, text=True)
    assert (on.returncode, on.stdout, on.stderr) == (off.returncode, off.stdout, off.stderr)
    if "VISUALIZE" in fragment and "--no-execute" in extra_flags:
        expected_status = 0
    assert on.returncode == expected_status
