"""Backend ranges select the offending raw text, independent of AST constructors."""

from dataclasses import fields

import pytest

from src.ast import (
    AggregateStmt, BinaryCondition, Comparison, FilterStmt, LoadStmt, PlotStmt,
    Program, SelectStmt, SortStmt, UnaryCondition, Value,
)
from src.editor.analysis import analyze_document
from src.lexer.lexer import Lexer
from src.parser.parser import Parser
from src.semantic.semantic import SemanticAnalysisError, SemanticAnalyzer


@pytest.fixture
def document(tmp_path):
    (tmp_path / "data.csv").write_text("label,amount,quantity\nA,2.5,2\n", encoding="utf-8")
    return tmp_path / "program.dl"


def selected_text(text, diagnostic):
    lines = text.split("\n")
    start = sum(len(line) + 1 for line in lines[:diagnostic.line - 1]) + diagnostic.column
    end = sum(len(line) + 1 for line in lines[:diagnostic.end_line - 1]) + diagnostic.end_column
    return text[start:end]


@pytest.mark.parametrize("statement,target", [
    ("SELECT amount, absent FROM sales;", "absent"),
    ("FILTER sales WHERE absent > 0;", "absent"),
    ("SORT absent FROM sales;", "absent"),
    ("AGGREGATE SUM(absent) FROM sales;", "absent"),
    ("AGGREGATE SUM(amount) FROM sales GROUP BY absent;", "absent"),
    ("VISUALIZE BAR OF absent FROM sales;", "absent"),
    ("SELECT quantity FROM absent;", "absent"),
    ("FILTER absent WHERE amount > 0;", "absent"),
    ('FILTER sales WHERE amount > "two\\nunits";', '"two\\nunits"'),
    ('FILTER sales WHERE amount == "two";', '"two"'),
    ("FILTER sales WHERE label == 123;", "123"),
    ("FILTER sales WHERE label > 0;", "label"),
    ("AGGREGATE SUM(label) FROM sales;", "label"),
    ("VISUALIZE LINE OF label FROM sales;", "label"),
    ('LOAD "absent.csv" AS other;', '"absent.csv"'),
    ('LOAD "data.csv" AS sales;', "sales"),
])
def test_semantic_ranges_select_exact_reference_or_literal(document, statement, target):
    text = 'LOAD "data.csv" AS sales;\n  ' + statement
    result = analyze_document(text, document, 1)
    error, = result.diagnostics
    assert error.stage == "semantic"
    assert error.line == error.end_line == 2
    assert selected_text(text, error) == target


@pytest.mark.parametrize("projection,statement,target", [
    ("SELECT label FROM sales;", "SELECT amount FROM sales;", "amount"),
    ("SELECT amount FROM sales;", "FILTER sales WHERE quantity > 0;", "quantity"),
    ("AGGREGATE SUM(amount) FROM sales;", "SORT amount FROM sales;", "amount"),
])
def test_removed_columns_use_the_current_schema_and_exact_reference(document, projection, statement, target):
    text = 'LOAD "data.csv" AS sales;\n' + projection + '\n' + statement
    result = analyze_document(text, document, 2)
    error, = result.diagnostics
    assert "does not exist" in error.message
    assert error.line == 3 and selected_text(text, error) == target
    assert result.statements[-1].before == result.statements[-1].after


def test_multiline_repeated_and_unicode_identifiers_keep_distinct_spans(document):
    text = 'LOAD "data.csv" AS sales; FILTER sales WHERE label == "😀"; SELECT\r\n label,\r\n sales, 未知 FROM sales;'
    result = analyze_document(text, document, 3)
    assert [selected_text(text, error) for error in result.diagnostics] == ["sales", "未知"]
    assert [(error.line, error.column) for error in result.diagnostics] == [(3, 1), (3, 8)]


@pytest.mark.parametrize("text,target,stage", [
    ('SELECT amount WRONG sales;', "WRONG", "syntax"),
    ('LOAD "data.csv" AS sales', "", "syntax"),
    ('# 😀\r\nSELECT amount FROM ;', ";", "syntax"),
    ('LOAD "😀.csv" WRONG sales;', "WRONG", "syntax"),
    ('@', "@", "lexical"),
    ('😀', "😀", "lexical"),
    ('123abc', "123abc", "lexical"),
    ('"unclosed\nstring', '"unclosed\nstring', "lexical"),
])
def test_frontend_ranges_cover_raw_tokens_and_eof(document, text, target, stage):
    error, = analyze_document(text, document, 4).diagnostics
    assert error.stage == stage
    assert selected_text(text, error) == target


def test_multiline_string_type_mismatch_covers_the_raw_literal(document):
    text = 'LOAD "data.csv" AS sales;\nFILTER sales WHERE amount == "😀\ntext";'
    error, = analyze_document(text, document, 5).diagnostics
    assert error.line == 2 and error.end_line == 3
    assert selected_text(text, error) == '"😀\ntext"'


def test_ast_metadata_preserves_all_positional_constructors_and_equality(document):
    value = Value(1, 0, "INT", 1)
    comparison = Comparison(1, 0, "amount", "GT", value)
    nodes = [LoadStmt(1, 0, "data.csv", "sales"), SelectStmt(1, 0, ["amount"], "sales"),
             FilterStmt(1, 0, "sales", comparison), PlotStmt(1, 0, "BAR", "amount", "sales"),
             AggregateStmt(1, 0, "SUM", "amount", "sales"), SortStmt(1, 0, "amount", "sales"),
             value, comparison, UnaryCondition(1, 0, "NOT", comparison),
             BinaryCondition(1, 0, "AND", comparison, comparison)]
    program = Program(1, 0, nodes)
    for node in [program, *nodes]:
        clone = type(node)(*(getattr(node, field.name) for field in fields(node) if field.init))
        assert node == clone and node.spans == {}
    parsed, = Parser(Lexer('SELECT amount FROM sales;').tokenize()).parse().statements
    assert parsed == nodes[1]
    assert parsed.spans["columns[0]"].column == 7
    assert nodes[4].group_by is None and nodes[5].ascending is True

    # Legacy manually constructed trees still report their original location.
    legacy = Program(1, 0, [nodes[0], SelectStmt(2, 3, ["absent"], "sales")])
    with pytest.raises(SemanticAnalysisError) as failure:
        SemanticAnalyzer(document.parent).analyze(legacy)
    error, = failure.value.errors
    assert (error.line, error.column, error.span) == (2, 3, None)
