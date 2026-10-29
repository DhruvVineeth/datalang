"""Driver failure stages and prevention, using specification-invalid programs."""

import pytest

from src.main import compile_source
from spec_oracles import FIXTURES


@pytest.mark.parametrize("fragment,stage,reason", [
    ("FILTER orders WHERE Amount = 1;", "Lexical", "did you mean =="),
    ("AGGREGATE COUNT(*) FROM orders;", "Lexical", "Unexpected character"),
    ("AGGREGATE SUM(Amount), AVG(Amount) FROM orders;", "Syntax", "Expected 'FROM'"),
    ("SORT Amount DOWN FROM orders;", "Syntax", "Expected 'FROM'"),
    ("SELECT Team FROM orders", "Syntax", "Expected ';'"),
    ("SORT amount FROM orders;", "Semantic", "amount"),
    ("SORT Amount FROM Orders;", "Semantic", "Orders"),
    ("AGGREGATE MIN(Team) FROM orders;", "Semantic", "numeric column"),
    ("SELECT Team FROM orders; SORT Amount FROM orders;", "Semantic", "Amount"),
    ("SELECT Team, Team FROM orders; FILTER orders WHERE Team == \"a\";", "Semantic", "ambiguous"),
    ("AGGREGATE SUM(Amount) FROM orders GROUP BY Team; SELECT Amount FROM orders;", "Semantic", "Amount"),
    ("VISUALIZE PIE OF Amount FROM orders;", "Semantic", "Unsupported chart type"),
])
@pytest.mark.parametrize("flags", [{}, {"dump_ast": True, "dump_ir": True, "execute": False}])
def test_invalid_programs_never_reach_execution(monkeypatch, capsys, fragment, stage, reason, flags):
    def forbidden(*args, **kwargs):
        pytest.fail("Failed validation reached IR, optimization, runtime loading or plotting")

    monkeypatch.setattr("src.main.IRGenerator.generate", forbidden)
    monkeypatch.setattr("src.main.optimize_ir", forbidden)
    monkeypatch.setattr("src.main.ExecutionEngine", forbidden)
    monkeypatch.setattr("src.executor.DataAnalysisModule.load", forbidden)
    monkeypatch.setattr("src.executor.VisualizationModule.plot", forbidden)
    assert compile_source('LOAD "orders.csv" AS orders;\n  ' + fragment, FIXTURES, **flags) == 1
    output = capsys.readouterr().out
    assert stage + " error at line 2, column " in output
    assert reason in output
    assert "Result (" not in output and "Semantic analysis passed." not in output


def test_runtime_empty_plot_stops_later_loads_and_keeps_last_valid_state(run_spec):
    run = run_spec('''LOAD "orders.csv" AS orders;
FILTER orders WHERE row > 9;
  VISUALIZE LINE OF Amount FROM orders;
LOAD "orders.csv" AS later;''')
    assert run.status == 1
    assert "Runtime error: Instruction 3 (PLOT)" in run.stdout
    assert "no non-null values" in run.stdout and "line 3, column 2" in run.stdout
    assert "Result (" not in run.stdout
    assert list(run.engine.tables) == ["T1", "T2"]
    assert run.engine.bindings == {"orders": "T2"}
    assert run.engine.result().empty
    assert run.charts == []


def test_compile_only_validates_without_constructing_executor(run_spec):
    run = run_spec('''LOAD "orders.csv" AS orders;
AGGREGATE SUM(Amount) FROM orders GROUP BY Team;
VISUALIZE LINE OF sum_Amount FROM orders;''', execute=False, dump_ir=True)
    assert run.status == 0 and run.engine is None and run.charts == []
    assert "AGGREGATE SUM(Amount) GROUP BY Team" in run.stdout
    assert "Result (" not in run.stdout
