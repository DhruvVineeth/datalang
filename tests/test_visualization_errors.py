"""Render real Matplotlib artists headlessly and check compiler diagnostics."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import pytest

from src.executor import ExecutionEngine, ExecutionError, VisualizationModule
from src.interpreter.ir import ComparePred, FilterIR, IRProgram, LoadIR
from src.lexer.lexer import Lexer, TokenType
from src.main import compile_source


@pytest.mark.parametrize("chart", ["BAR", "LINE", "SCATTER"])
def test_render_chart(chart):
    frame = pd.DataFrame({"value": [3, 7, 3]})
    figure = VisualizationModule(show=False).plot(frame, chart, "value")
    try:
        axes = figure.axes[0]
        if chart == "BAR":
            assert [bar.get_height() for bar in axes.patches] == [2, 1]
        elif chart == "LINE":
            assert list(axes.lines[0].get_ydata()) == [3, 7, 3]
        else:
            assert axes.collections[0].get_offsets().tolist() == [[0, 3], [1, 7], [2, 3]]
        figure.canvas.draw()
    finally:
        plt.close(figure)


@pytest.mark.parametrize("frame,chart,column,message", [
    (pd.DataFrame({"x": []}), "BAR", "x", "no non-null"),
    (pd.DataFrame({"x": [None]}), "LINE", "x", "no non-null"),
    (pd.DataFrame({"x": ["a"]}), "SCATTER", "x", "numeric"),
    (pd.DataFrame({"x": [float("inf")]}), "LINE", "x", "finite"),
    (pd.DataFrame({"x": [1]}), "BAR", "missing", "not in"),
    (pd.DataFrame({"x": [1]}), "PIE", "x", "Unsupported"),
])
def test_invalid_plot(frame, chart, column, message):
    with pytest.raises(ExecutionError, match=message):
        VisualizationModule(show=False).plot(frame, chart, column)


@pytest.mark.parametrize("source,stage", [
    ("@ $", "Lexical"),
    ('LOAD "unterminated', "Lexical"),
    ('LOAD "data.csv" AS data', "Syntax"),
    ("SELECT missing FROM data;", "Semantic"),
])
def test_compile_error_stages(source, stage, tmp_path, capsys):
    assert compile_source(source, tmp_path) == 1
    output = capsys.readouterr().out
    assert f"{stage} error" in output
    assert "line 1" in output


def test_runtime_type_error_has_instruction_context(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text("x\nhello\n", encoding="utf-8")
    program = IRProgram([
        LoadIR(str(path), "T1", "data"),
        FilterIR("T1", ComparePred("x", "GT", 1), "T2"),
    ])
    with pytest.raises(ExecutionError, match=r"Instruction 2 \(FILTER\)"):
        ExecutionEngine().execute(program)


def test_missing_runtime_file(tmp_path):
    with pytest.raises(ExecutionError, match="file not found"):
        ExecutionEngine().execute(IRProgram([LoadIR(str(tmp_path / "gone.csv"), "T1", "data")]))


def test_runtime_error_reported_by_driver(tmp_path, capsys):
    (tmp_path / "data.csv").write_text("x\n1\n", encoding="utf-8")
    source = 'LOAD "data.csv" AS data; FILTER data WHERE x > 5; VISUALIZE LINE OF x FROM data;'
    assert compile_source(source, tmp_path) == 1
    assert "Runtime error:" in capsys.readouterr().out


def test_lexical_locations_after_multiline_string():
    tokens = Lexer('"hello\nworld"\n  @').tokenize()
    assert (tokens[0].line, tokens[0].column) == (1, 0)
    error = next(token for token in tokens if token.type == TokenType.ERROR)
    assert (error.line, error.column) == (3, 2)


def test_unsupported_chart_is_semantic_error(tmp_path, capsys):
    (tmp_path / "data.csv").write_text("x\n1\n", encoding="utf-8")
    assert compile_source('LOAD "data.csv" AS data; VISUALIZE PIE OF x FROM data;', tmp_path) == 1
    assert "Semantic error" in capsys.readouterr().out


def test_plot_backend_failure_has_runtime_context(tmp_path, monkeypatch):
    from src.interpreter.ir import PlotIR

    path = tmp_path / "data.csv"
    path.write_text("x\n1\n", encoding="utf-8")
    def fail_show():
        raise OSError("display unavailable")
    monkeypatch.setattr(plt, "show", fail_show)
    before = plt.get_fignums()
    with pytest.raises(ExecutionError, match=r"Instruction 2 \(PLOT\): display unavailable"):
        ExecutionEngine().execute(IRProgram([
            LoadIR(str(path), "T1", "data"), PlotIR("T1", "LINE", "x"),
        ]))
    assert plt.get_fignums() == before
