"""Editor buffers use only the existing frontend and CSV schema inference."""

import csv
from dataclasses import FrozenInstanceError, asdict
import json
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
    assert result.statements == ()
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
    assert result.statements == ()
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
        ("semantic", 3, 7), ("semantic", 5, 4), ("semantic", 6, 4)
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
    assert (error.stage, error.line, error.column) == ("semantic", 2, 7)
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
    failed = result.statements[-1]
    assert not failed.is_valid
    assert failed.before == failed.after == result.statements[-2].after


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
    # Loading the same file twice must still create independent histories.
    assert result.schema_at(9, 0).name == "right"
    assert fields(result.schema_at(9, 0)) == [
        ("label", STRING), ("amount", NUMERIC), ("quantity", INTEGER),
    ]
    assert fields(result.schema_at(8, 0)) == [("sum_amount", NUMERIC), ("label", STRING)]


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


def test_each_statement_exposes_its_input_and_output_schema(document):
    result = analyze_document('''LOAD "data.csv" AS sales;
SELECT amount, label FROM sales;
FILTER sales WHERE amount > 0;
SORT amount DESC FROM sales;
AGGREGATE SUM(amount) FROM sales GROUP BY label;
SELECT sum_amount FROM sales;
AGGREGATE AVG(sum_amount) FROM sales;
VISUALIZE LINE OF avg_sum_amount FROM sales;''', document, 10)

    original = [("label", STRING), ("amount", NUMERIC), ("quantity", INTEGER)]
    projected = [("amount", NUMERIC), ("label", STRING)]
    grouped = [("label", STRING), ("sum_amount", NUMERIC)]
    expected = [
        (None, original), (original, projected), (projected, projected),
        (projected, projected), (projected, grouped),
        (grouped, [("sum_amount", NUMERIC)]),
        ([("sum_amount", NUMERIC)], [("avg_sum_amount", NUMERIC)]),
        ([("avg_sum_amount", NUMERIC)], [("avg_sum_amount", NUMERIC)]),
    ]
    assert result.ok
    assert len(result.statements) == len(expected)
    for index, (snapshot, (before, after)) in enumerate(zip(result.statements, expected)):
        assert snapshot.statement_index == index
        assert snapshot.dataset_name == "sales" and snapshot.is_valid
        assert (fields(snapshot.before) if snapshot.before is not None else None) == before
        assert fields(snapshot.after) == after
        assert snapshot.after.file_path == str(document.with_name("data.csv"))
        assert result.schema_at(index + 1, 0) == snapshot.before
        assert result.schema_at(index + 1, 0, phase="after") == snapshot.after
    assert result.datasets == (result.statements[-1].after,)


def test_snapshot_order_and_duplicates_survive_preserving_and_later_transformations(document):
    result = analyze_document('''LOAD "data.csv" AS sales;
SELECT label, amount, label FROM sales;
FILTER sales WHERE amount > 0;
SORT amount FROM sales;
SELECT label, amount, label FROM sales;
AGGREGATE COUNT(amount) FROM sales;''', document, 11)

    repeated = [("label", STRING), ("amount", NUMERIC), ("label", STRING)]
    expanded = [("label", STRING)] * 2 + [("amount", NUMERIC)] + [("label", STRING)] * 2
    assert result.ok
    assert fields(result.statements[0].after) == [
        ("label", STRING), ("amount", NUMERIC), ("quantity", INTEGER),
    ]
    for snapshot in result.statements[2:4]:
        assert fields(snapshot.before) == fields(snapshot.after) == repeated
    assert fields(result.statements[1].after) == repeated
    assert fields(result.statements[4].after) == expanded
    assert fields(result.statements[5].before) == expanded
    assert fields(result.statements[5].after) == [("count_amount", INTEGER)]


def test_position_lookup_uses_only_the_referenced_dataset_at_that_time(document):
    document.with_name("text.csv").write_text("amount,other\ntext,value\n", encoding="utf-8")
    result = analyze_document('''LOAD "data.csv" AS left;
LOAD "text.csv" AS right;
SELECT amount FROM left;
FILTER right WHERE amount == "text";
AGGREGATE SUM(amount) FROM left;
SORT amount FROM right;
AGGREGATE COUNT(amount) FROM right;
SELECT sum_amount FROM left;''', document, 12)

    assert result.ok
    assert result.statements[0].before is result.statements[1].before is None
    assert result.schema_at(3, 5).name == "left"
    assert fields(result.schema_at(3, 5)) == [
        ("label", STRING), ("amount", NUMERIC), ("quantity", INTEGER),
    ]
    assert result.schema_at(4, 5).name == "right"
    assert fields(result.schema_at(4, 5)) == [("amount", STRING), ("other", STRING)]
    assert fields(result.schema_at(5, 5)) == [("amount", NUMERIC)]
    assert fields(result.schema_at(6, 5)) == [("amount", STRING), ("other", STRING)]
    assert fields(result.schema_at(8, 5)) == [("sum_amount", NUMERIC)]
    assert [fields(dataset) for dataset in result.datasets] == [
        [("sum_amount", NUMERIC)], [("count_amount", INTEGER)],
    ]


@pytest.mark.parametrize("invalid", [
    "SELECT amount, missing, label FROM sales;",
    'FILTER sales WHERE amount > 0 AND label == 1;',
    "SORT missing FROM sales;",
    "AGGREGATE SUM(label) FROM sales;",
    "AGGREGATE SUM(amount) FROM sales GROUP BY missing;",
    'LOAD "other.csv" AS sales;',
])
def test_invalid_statement_snapshots_keep_the_last_valid_state(document, invalid):
    result = analyze_document(f'''LOAD "data.csv" AS sales;
SELECT amount, label FROM sales;
{invalid}
FILTER sales WHERE amount > 0;
AGGREGATE SUM(amount) FROM sales;''', document, 13)

    assert not result.ok and len(result.diagnostics) == 1
    assert [snapshot.is_valid for snapshot in result.statements] == [True, True, False, True, True]
    failed = result.statements[2]
    assert fields(failed.before) == [("amount", NUMERIC), ("label", STRING)]
    assert failed.before == failed.after == result.statements[3].before
    assert result.schema_at(3, 0, phase="after") == failed.before
    assert fields(result.statements[-1].after) == [("sum_amount", NUMERIC)]


def test_unloaded_and_failed_load_statements_have_no_partial_schemas(document):
    result = analyze_document('''FILTER missing WHERE amount > 0;
LOAD "absent.csv" AS missing;
LOAD "data.csv" AS missing;
SELECT quantity FROM missing;''', document, 14)

    assert not result.ok and len(result.diagnostics) == 2
    for snapshot in result.statements[:2]:
        assert snapshot.dataset_name == "missing" and not snapshot.is_valid
        assert snapshot.before is snapshot.after is None
    assert result.schema_at(1, 5) is result.schema_at(2, 5, phase="after") is None
    assert result.statements[2].before is None and result.statements[2].is_valid
    assert fields(result.statements[2].after) == [
        ("label", STRING), ("amount", NUMERIC), ("quantity", INTEGER),
    ]
    assert fields(result.statements[3].after) == [("quantity", INTEGER)]


def test_source_ranges_cover_multiline_and_adjacent_statements_with_exact_boundaries(document):
    source = ('# leading comment\r\n  LOAD "data.csv" AS sales;SELECT\r\n'
              ' amount, # ; comment\r\n label FROM sales; FILTER sales WHERE label == "B;\u00e9"; # trailing\r\n')
    result = analyze_document(source, document, 15)
    assert result.ok
    load, select, filter_stmt = result.statements
    assert asdict(load.source_range) == {
        "start_line": 2, "start_column": 2, "end_line": 2, "end_column": 27,
    }
    assert asdict(select.source_range) == {
        "start_line": 2, "start_column": 27, "end_line": 4, "end_column": 18,
    }
    assert result.statement_at(2, 26) == load  # terminating semicolon
    assert result.statement_at(2, 27) == select  # adjacent statement
    assert result.statement_at(3, 1) == select  # multiline body
    assert result.statement_at(4, 17) == select
    assert result.statement_at(4, 18) is None  # space between statements
    assert result.statement_at(4, 19) == filter_stmt
    assert result.statement_at(4, filter_stmt.source_range.end_column - 1) == filter_stmt
    for line, column in [(0, 0), (1, 0), (2, -1), (2, 1), (5, 0), (99, 0),
                         (4, filter_stmt.source_range.end_column)]:
        assert result.statement_at(line, column) is None
        assert result.schema_at(line, column) is None
    with pytest.raises(ValueError, match="phase"):
        result.schema_at(3, 1, phase="invalid")


def test_snapshots_are_frozen_serializable_and_stable_across_reanalysis(document):
    source = 'LOAD "data.csv" AS sales; SELECT amount FROM sales;'
    first = analyze_document(source, document, 16)
    second = analyze_document(source, document, 16)
    serialized = json.loads(json.dumps(asdict(first)))
    assert serialized == json.loads(json.dumps(asdict(second)))
    assert [item["statement_index"] for item in serialized["statements"]] == [0, 1]

    snapshot = first.statements[0]
    with pytest.raises(FrozenInstanceError):
        snapshot.is_valid = False
    with pytest.raises(FrozenInstanceError):
        snapshot.source_range.end_column = 0
    with pytest.raises(FrozenInstanceError):
        snapshot.after.columns = ()
    with pytest.raises(FrozenInstanceError):
        snapshot.after.columns[0].data_type = "changed"

    document.with_name("data.csv").write_text("changed\ntext\n", encoding="utf-8")
    analyze_document('LOAD "data.csv" AS sales;', document, 17)
    assert json.loads(json.dumps(asdict(first))) == serialized
