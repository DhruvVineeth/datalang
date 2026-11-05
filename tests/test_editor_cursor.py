"""Incomplete editor context uses tokens, the strict grammar and checked prefixes."""

from dataclasses import FrozenInstanceError, asdict
import json

import pytest

from src.editor import analyze_cursor, analyze_document
from src.lexer.lexer import Lexer
from src.main import compile_source
from src.parser.parser import ParseError, Parser
from src.symbol_table.symbol_table import INTEGER, NUMERIC, STRING


ORIGINAL = [("label", STRING), ("amount", NUMERIC), ("quantity", INTEGER)]
PROJECTED = [("amount", NUMERIC), ("label", STRING)]


@pytest.fixture
def document(tmp_path):
    contents = "label,amount,quantity\nB,2.5,2\nA,1,1\n"
    (tmp_path / "data.csv").write_text(contents, encoding="utf-8")
    (tmp_path / "semi;data.csv").write_text(contents, encoding="utf-8")
    (tmp_path / "text.csv").write_text("amount,other\ntext,value\n", encoding="utf-8")
    return tmp_path / "unsaved.dl"


def at_cursor(marked_text, document, version=1):
    before, marker, after = marked_text.partition("<cursor>")
    assert marker and "<cursor>" not in after
    return analyze_cursor(
        before + after, document, version,
        before.count("\n") + 1, len(before.rsplit("\n", 1)[-1]),
    )


def fields(schema):
    return None if schema is None else [(column.name, column.data_type) for column in schema.columns]


@pytest.mark.parametrize("unfinished", [
    "SELECT amount FROM sales<cursor>",
    "FILTER sales<cursor>",
    "FILTER sales WHERE <cursor>",
    "FILTER sales WHERE amount > <cursor>",
    "FILTER sales WHERE amount > 1 AND <cursor>",
    "SORT amount FROM sales<cursor>",
    "AGGREGATE SUM(amount) FROM sales<cursor>",
    "AGGREGATE SUM(amount) FROM sales GROUP BY <cursor>",
    "VISUALIZE LINE OF amount FROM sales<cursor>",
])
def test_unfinished_statements_use_the_checked_input_schema(document, unfinished):
    result = at_cursor('LOAD "data.csv" AS sales;\n' + unfinished, document, 7)

    assert result.prefix.document_version == 7
    assert result.prefix.document_path == str(document.resolve())
    assert result.schema_reliable and result.diagnostics == ()
    assert result.active_statement.dataset_name == "sales"
    assert not result.active_statement.is_complete
    assert fields(result.input_schema) == ORIGINAL
    assert len(result.prefix.statements) == 1


def test_complete_pipeline_before_cursor_uses_existing_transformations(document):
    result = at_cursor('''LOAD "data.csv" AS sales;
SELECT amount, label FROM sales;
FILTER sales WHERE amount > 0;
SORT amount DESC FROM sales;
AGGREGATE SUM(amount) FROM sales GROUP BY label;
FILTER sales WHERE <cursor>''', document)

    assert result.diagnostics == () and result.schema_reliable
    assert len(result.prefix.statements) == 5
    assert fields(result.prefix.statements[1].after) == PROJECTED
    assert fields(result.prefix.statements[2].after) == PROJECTED
    assert fields(result.prefix.statements[3].after) == PROJECTED
    assert fields(result.input_schema) == [("label", STRING), ("sum_amount", NUMERIC)]


@pytest.mark.parametrize("active", [
    "SELECT <cursor> FROM right;",
    "SELECT am<cursor>ount FROM right;",
    "SELECT amount, <cursor> FROM right;",
    "SELECT\n amount,\n <cursor>\n FROM\n right",
])
def test_select_columns_use_only_the_dataset_later_in_the_same_statement(document, active):
    result = at_cursor('''LOAD "data.csv" AS left;
LOAD "text.csv" AS right;
SELECT quantity FROM left;
''' + active + '\nSELECT other FROM right;', document)

    assert result.schema_reliable and result.diagnostics == ()
    assert result.active_statement.kind == "SELECT"
    assert result.active_statement.dataset_name == "right"
    assert fields(result.input_schema) == [("amount", STRING), ("other", STRING)]
    assert fields(result.prefix.datasets[0]) == [("quantity", INTEGER)]
    assert len(result.prefix.statements) == 3


@pytest.mark.parametrize("active", [
    "SELECT <cursor>",
    "SELECT amount, <cursor>",
    "SELECT\n amount,\n <cursor>",
    "SELECT <cursor>; SELECT amount FROM left;",
    'SELECT <cursor> # FROM right;\n',
])
def test_select_without_from_provides_assistance_without_guessing_scope(document, active):
    result = at_cursor('''LOAD "data.csv" AS left;
LOAD "text.csv" AS right;
''' + active, document)

    assert result.schema_reliable and result.diagnostics == ()
    assert result.active_statement.dataset_name is None
    assert result.input_schema is None
    assert "FROM" in result.keywords
    assert result.dataset_names == ("left", "right")


@pytest.mark.parametrize("active", [
    "SELECT amount FROM <cursor>",
    "FILTER <cursor>",
    "SORT amount FROM <cursor>",
    "AGGREGATE SUM(amount) FROM <cursor>",
    "VISUALIZE LINE OF amount FROM <cursor>",
])
def test_unfinished_dataset_slots_offer_dataset_assistance_without_a_schema(document, active):
    result = at_cursor('LOAD "data.csv" AS sales;\n' + active, document)

    assert result.schema_reliable and result.diagnostics == ()
    assert result.input_schema is None and result.active_statement.dataset_name is None
    assert result.dataset_names == ("sales",)
    assert "FROM" not in result.keywords


def test_active_statement_is_not_applied_and_future_transformations_are_ignored(document):
    result = at_cursor('''LOAD "data.csv" AS sales;
SELECT am<cursor>ount FROM sales;
AGGREGATE SUM(amount) FROM sales;''', document)

    assert result.active_statement.is_complete
    assert fields(result.input_schema) == ORIGINAL
    assert len(result.prefix.statements) == 1
    assert fields(result.prefix.datasets[0]) == ORIGINAL


def test_multiline_active_statement_keeps_duplicate_order_and_dataset_isolation(document):
    result = at_cursor('''LOAD "data.csv" AS left;
LOAD "data.csv" AS right;
SELECT label, amount, label FROM left;
SELECT quantity FROM right;
FILTER left
WHERE
 amount > <cursor>''', document)

    assert result.schema_reliable
    assert fields(result.input_schema) == [("label", STRING), ("amount", NUMERIC), ("label", STRING)]
    assert fields(result.prefix.datasets[1]) == [("quantity", INTEGER)]
    assert result.active_statement.source_range.start_line == 5
    assert result.active_statement.source_range.end_line == 7


@pytest.mark.parametrize("literal", ['"B;C"', '"B;\\\";C"', '"B;\nC"'])
def test_semicolons_inside_strings_and_comments_are_never_statement_boundaries(document, literal):
    result = at_cursor('''LOAD "semi;data.csv" AS sales;
FILTER sales WHERE label == ''' + literal + '''; # ; FROM unrelated
SELECT <cursor> FROM sales;''', document)

    assert result.diagnostics == () and result.schema_reliable
    assert len(result.prefix.statements) == 2
    assert result.active_statement.statement_index == 2
    assert fields(result.input_schema) == ORIGINAL


def test_unclosed_string_does_not_create_fake_statements_or_dataset_scope(document):
    result = at_cursor('''LOAD "data.csv" AS sales;
FILTER sales WHERE label == "unfinished; FROM unrelated;
still a string<cursor>''', document)

    assert result.diagnostics == () and result.schema_reliable
    assert len(result.prefix.statements) == 1
    assert result.active_statement.kind == "FILTER"
    assert result.active_statement.dataset_name == "sales"
    assert result.active_statement.statement_index == 1
    assert fields(result.input_schema) == ORIGINAL


@pytest.mark.parametrize("broken", [
    "SELECT amount sales;",          # missing FROM
    "SELECT amount, FROM sales;",    # missing column
    "FILTER sales WHERE amount >;", # missing value
    "@;",                           # lexical error
])
def test_earlier_error_stops_propagation_and_suppresses_dependent_semantics(document, broken):
    result = at_cursor('''LOAD "data.csv" AS sales;
''' + broken + '''
LOAD "does-not-exist.csv" AS later;
SELECT missing FROM sales;
FILTER sales WHERE <cursor>''', document)

    assert not result.schema_reliable
    assert len(result.prefix.statements) == 1
    assert fields(result.prefix.datasets[0]) == ORIGINAL
    assert result.active_statement.dataset_name == "sales"
    assert result.active_statement.statement_index == 4
    assert result.input_schema is None
    assert len(result.diagnostics) == 1
    assert result.diagnostics[0].stage in {"syntax", "lexical"}
    assert not any(error.stage == "semantic" for error in result.diagnostics)


def test_missing_semicolon_before_cursor_is_an_uncertainty_barrier(document):
    result = at_cursor('''LOAD "data.csv" AS sales;
SELECT amount FROM sales
FILTER sales WHERE <cursor>''', document)

    assert not result.schema_reliable and result.input_schema is None
    assert len(result.prefix.statements) == 1
    assert fields(result.prefix.datasets[0]) == ORIGINAL
    assert len(result.diagnostics) == 1
    assert result.diagnostics[0].stage == "syntax"
    assert result.diagnostics[0].line == 3


def test_invalid_syntax_inside_active_prefix_does_not_publish_a_schema(document):
    result = at_cursor('''LOAD "data.csv" AS sales;
SELECT amount,, <cursor> FROM sales;''', document)

    assert not result.schema_reliable and result.input_schema is None
    assert len(result.diagnostics) == 1 and result.diagnostics[0].stage == "syntax"


def test_future_errors_do_not_hide_the_active_input_schema(document):
    result = at_cursor('''LOAD "data.csv" AS sales;
SELECT <cursor> FROM sales;
@ LOAD "unfinished; string''', document)

    assert result.schema_reliable and result.diagnostics == ()
    assert fields(result.input_schema) == ORIGINAL


def test_semantic_failure_in_complete_prefix_keeps_last_valid_schema(document):
    result = at_cursor('''LOAD "data.csv" AS sales;
SELECT amount, missing FROM sales;
FILTER sales WHERE <cursor>''', document)

    assert result.schema_reliable
    assert fields(result.input_schema) == ORIGINAL
    assert len(result.diagnostics) == 1 and result.diagnostics[0].stage == "semantic"
    assert not result.prefix.statements[-1].is_valid


@pytest.mark.parametrize("text,expected", [
    ("SEL<cursor>", "SELECT"),
    ("SELECT amount FRO<cursor>", "FROM"),
    ("FILTER sales WHE<cursor>", "WHERE"),
])
def test_keyword_fragments_are_editor_assistance_not_syntax_errors(document, text, expected):
    result = at_cursor('LOAD "data.csv" AS sales;\n' + text, document)
    assert result.schema_reliable and result.diagnostics == ()
    assert expected in result.keywords


def test_new_edits_do_not_reuse_old_or_unrelated_schemas(document):
    first = at_cursor('LOAD "data.csv" AS sales; SELECT <cursor> FROM sales;', document, 1)
    second = at_cursor('LOAD "text.csv" AS other; SELECT <cursor> FROM other;', document, 2)
    removed = at_cursor('SELECT <cursor> FROM sales;', document, 3)

    assert fields(first.input_schema) == ORIGINAL
    assert second.input_schema.name == "other"
    assert fields(second.input_schema) == [("amount", STRING), ("other", STRING)]
    assert removed.input_schema is None and removed.dataset_names == ()
    assert [result.prefix.document_version for result in (first, second, removed)] == [1, 2, 3]
    document.with_name("data.csv").write_text("changed\ntext\n", encoding="utf-8")
    refreshed = at_cursor('LOAD "data.csv" AS sales; SELECT <cursor> FROM sales;', document, 4)
    assert fields(refreshed.input_schema) == [("changed", STRING)]
    assert fields(first.input_schema) == ORIGINAL


def test_context_and_prefix_snapshots_are_immutable_and_serializable(document):
    result = at_cursor('LOAD "data.csv" AS sales; SELECT <cursor> FROM sales;', document)
    assert json.loads(json.dumps(asdict(result)))["active_statement"]["statement_index"] == 1
    with pytest.raises(FrozenInstanceError):
        result.active_statement.dataset_name = "other"
    with pytest.raises(FrozenInstanceError):
        result.input_schema.columns[0].name = "other"


@pytest.mark.parametrize("tail", ["", "\n# ; comment\n", "\r\n  "])
def test_between_statements_and_at_eof_offer_keywords_without_default_scope(document, tail):
    result = at_cursor('LOAD "data.csv" AS sales;' + tail + '<cursor>', document)
    assert result.active_statement is None and result.input_schema is None
    assert "SELECT" in result.keywords and result.dataset_names == ("sales",)
    assert len(result.prefix.statements) == 1


@pytest.mark.parametrize("line,column", [(0, 0), (1, -1), (1, 1000), (3, 0)])
def test_cursor_coordinates_are_validated(document, line, column):
    with pytest.raises(ValueError, match="cursor"):
        analyze_cursor("SELECT\n", document, 1, line, column)


def test_strict_compilation_and_document_analysis_still_reject_incomplete_input(document, capsys):
    source = 'LOAD "data.csv" AS sales;\nFILTER sales WHERE amount >'
    cursor = at_cursor(source + '<cursor>', document)
    assert cursor.schema_reliable and fields(cursor.input_schema) == ORIGINAL
    with pytest.raises(ParseError):
        Parser(Lexer(source).tokenize()).parse()
    strict = analyze_document(source, document, 1)
    assert not strict.ok and strict.datasets == strict.statements == ()
    assert compile_source(source, source_dir=document.parent, execute=False) == 1
    assert "Syntax error" in capsys.readouterr().out
