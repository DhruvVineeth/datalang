"""Editor buffers use only the existing frontend and CSV schema inference."""

import csv
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from src.editor.analysis import analyze_document
from src.symbol_table.symbol_table import INTEGER, NUMERIC, STRING


@pytest.fixture
def document(tmp_path):
    directory = tmp_path / "project"
    directory.mkdir()
    (directory / "data.csv").write_text(
        "label,amount,quantity\nB,2.5,2\nA,1,1\n", encoding="utf-8"
    )
    return directory / "program.dl"


def fields(dataset):
    return [(column.name, column.data_type) for column in dataset.columns]


def test_current_buffer_and_document_relative_loads(document, tmp_path, monkeypatch):
    document.write_text("invalid text on disk", encoding="utf-8")
    # A conflicting CSV in cwd must not influence the document's schema.
    (tmp_path / "data.csv").write_text("wrong\n0\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = analyze_document(
        text='LOAD "data.csv" AS sales;',
        document_path=document,
        document_version=17,
    )

    assert result.ok and result.diagnostics == ()
    assert result.document_path == str(document.resolve())
    assert result.document_version == 17
    assert len(result.datasets) == 1
    dataset = result.datasets[0]
    assert dataset.name == "sales"
    assert dataset.file_path == str(document.with_name("data.csv"))
    assert fields(dataset) == [("label", STRING), ("amount", NUMERIC), ("quantity", INTEGER)]
    assert Path.cwd() == tmp_path


def test_relative_document_parent_paths_and_absolute_loads(document, tmp_path, monkeypatch):
    (tmp_path / "shared.csv").write_text("x\n3\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    absolute_csv = document.with_name("data.csv").as_posix()
    result = analyze_document(
        f'LOAD "../shared.csv" AS shared; LOAD "{absolute_csv}" AS sales;',
        Path("project") / document.name,
        1,
    )
    assert result.ok
    assert result.document_path == str(document)
    assert [dataset.name for dataset in result.datasets] == ["shared", "sales"]
    assert fields(result.datasets[0]) == [("x", INTEGER)]
    assert fields(result.datasets[1])[0] == ("label", STRING)
    assert not document.exists()


def test_all_lexical_errors_stop_before_parsing(document, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Lexical failure reached parsing")

    monkeypatch.setattr("src.editor.analysis.Parser.parse", forbidden)
    result = analyze_document("# comment\r\n  @ $\n!", document, 2)

    assert not result.ok and result.datasets == ()
    assert [(error.stage, error.line, error.column) for error in result.diagnostics] == [
        ("lexical", 2, 2), ("lexical", 2, 4), ("lexical", 3, 0)
    ]
    assert all(error.severity == "error" for error in result.diagnostics)
    assert result.diagnostics[0].message == "Unexpected character: @"
    assert result.document_version == 2


@pytest.mark.parametrize("text,line,column,message", [
    ('LOAD "data.csv" AS sales', 1, 24, "end of input"),
    ("\n  FILTER sales WHERE amount >;", 2, 29, "Expected a value"),
])
def test_structured_syntax_errors_stop_before_semantics(document, monkeypatch, text, line, column, message):
    def forbidden(*args, **kwargs):
        raise AssertionError("Syntax failure reached semantic analysis")

    monkeypatch.setattr("src.editor.analysis.SemanticAnalyzer.analyze", forbidden)
    result = analyze_document(text, document, 3)

    assert not result.ok and result.datasets == ()
    assert len(result.diagnostics) == 1
    error = result.diagnostics[0]
    assert (error.stage, error.line, error.column) == ("syntax", line, column)
    assert message in error.message
    assert not error.message.startswith("Syntax error")


def test_semantic_errors_retain_comparison_locations_and_valid_schemas(document):
    result = analyze_document('''LOAD "data.csv" AS sales;
SELECT label, amount FROM sales;
SELECT quantity FROM sales;
FILTER sales WHERE
    missing > 0 OR
    label > 0;''', document, 4)

    assert not result.ok
    assert [(error.stage, error.line, error.column) for error in result.diagnostics] == [
        ("semantic", 3, 0), ("semantic", 5, 4), ("semantic", 6, 4)
    ]
    assert "quantity" in result.diagnostics[0].message
    assert "missing" in result.diagnostics[1].message
    assert "not applicable" in result.diagnostics[2].message
    assert fields(result.datasets[0]) == [("label", STRING), ("amount", NUMERIC)]


@pytest.mark.parametrize("contents,message", [
    (None, "not found"),
    (b"", "empty"),
    (b"\xff", "codec"),
    (b"x\n" + b"a" * (csv.field_size_limit() + 1), "field"),
], ids=["missing", "empty", "encoding", "oversized-field"])
def test_csv_failures_are_semantic_diagnostics(document, contents, message):
    if contents is not None:
        document.with_name("bad.csv").write_bytes(contents)
    result = analyze_document('\n  LOAD "bad.csv" AS broken;', document, 5)

    assert not result.ok and result.datasets == ()
    error, = result.diagnostics
    assert (error.stage, error.line, error.column) == ("semantic", 2, 2)
    assert "broken" in error.message and "bad.csv" in error.message
    assert message in error.message


def test_duplicate_projection_order_and_expansion_are_preserved(document):
    result = analyze_document('''LOAD "data.csv" AS sales;
SELECT label, amount, label FROM sales;
SELECT label, amount, label FROM sales;''', document, 6)

    assert result.ok
    assert fields(result.datasets[0]) == [
        ("label", STRING), ("label", STRING), ("amount", NUMERIC),
        ("label", STRING), ("label", STRING),
    ]


def test_ambiguous_duplicate_is_a_semantic_error_without_losing_columns(document):
    result = analyze_document('''LOAD "data.csv" AS sales;
SELECT amount, label, amount FROM sales;
SORT amount FROM sales;''', document, 7)

    assert not result.ok
    assert "ambiguous" in result.diagnostics[0].message
    assert fields(result.datasets[0]) == [("amount", NUMERIC), ("label", STRING), ("amount", NUMERIC)]


def test_schema_propagation_and_dataset_isolation(document):
    result = analyze_document('''LOAD "data.csv" AS left;
LOAD "data.csv" AS right;
SELECT label, amount FROM left;
FILTER left WHERE amount > 0;
SORT amount DESC FROM left;
AGGREGATE SUM(amount) FROM left GROUP BY label;
SELECT sum_amount, label FROM left;
SORT sum_amount FROM left;
SELECT quantity FROM right;''', document, 8)

    assert result.ok
    assert fields(result.datasets[0]) == [("sum_amount", NUMERIC), ("label", STRING)]
    assert fields(result.datasets[1]) == [("quantity", INTEGER)]


def test_reanalysis_uses_fresh_text_csv_and_state(document):
    first = analyze_document('LOAD "data.csv" AS sales; SELECT amount FROM sales;', document, 1)
    document.with_name("data.csv").write_text("changed\ntext\n", encoding="utf-8")
    second = analyze_document('LOAD "data.csv" AS sales;', document, 2)
    empty = analyze_document("# new empty buffer\n", document, 3)
    invalid = analyze_document("@", document, 4)

    assert first.ok and second.ok and empty.ok and not invalid.ok
    assert fields(first.datasets[0]) == [("amount", NUMERIC)]
    assert fields(second.datasets[0]) == [("changed", STRING)]
    assert empty.datasets == invalid.datasets == ()
    assert [result.document_version for result in (first, second, empty, invalid)] == [1, 2, 3, 4]
    with pytest.raises(FrozenInstanceError):
        first.datasets[0].columns[0].name = "changed"


def test_analysis_is_silent_read_only_and_never_reaches_later_stages(document, monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        raise AssertionError("Editor analysis reached the driver or a later stage")

    for target in (
        "src.main.compile_source",
        "src.interpreter.ir.IRGenerator.generate",
        "src.interpreter.optimizer.optimize_ir",
        "src.main.optimize_ir",
        "src.executor.ExecutionEngine.__init__",
        "src.executor.ExecutionEngine.execute",
        "src.executor.DataAnalysisModule.load",
        "src.executor.DataAnalysisModule.select",
        "src.executor.DataAnalysisModule.filter",
        "src.executor.DataAnalysisModule.sort",
        "src.executor.DataAnalysisModule.aggregate",
        "src.executor.VisualizationModule.plot",
        "pandas.read_csv",
    ):
        monkeypatch.setattr(target, forbidden)
    document.write_text("invalid text on disk", encoding="utf-8")
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in document.parent.iterdir()}
    result = analyze_document('''LOAD "data.csv" AS sales;
SELECT label, amount FROM sales;
FILTER sales WHERE amount > 1000;
SORT amount DESC FROM sales;
AGGREGATE SUM(amount) FROM sales GROUP BY label;
VISUALIZE LINE OF sum_amount FROM sales;''', document, 9)

    assert result.ok
    assert fields(result.datasets[0]) == [("label", STRING), ("sum_amount", NUMERIC)]
    assert {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in document.parent.iterdir()} == before
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""
