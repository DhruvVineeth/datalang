"""Sorting syntax preserves existing identifier tokens and statement forms."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.ast import SortStmt
from src.lexer.lexer import Lexer, TokenType
from src.parser.parser import ParseError, Parser, print_ast


@pytest.mark.parametrize("direction,ascending", [("", True), ("ASC", True), ("DESC", False), ("dEsC", False)])
def test_sort_ast(direction, ascending):
    statement = Parser(Lexer(f"\n  sOrT Revenue {direction} FROM sales;").tokenize()).parse().statements[0]
    assert isinstance(statement, SortStmt)
    assert (statement.column_name, statement.source, statement.ascending) == ("Revenue", "sales", ascending)
    assert (statement.line, statement.column) == (2, 2)


def test_sorting_words_remain_identifiers():
    assert [token.type for token in Lexer("sort asc desc").tokenize()] == [TokenType.ID] * 3 + [TokenType.EOF]
    program = Parser(Lexer('''LOAD "data.csv" AS sort;
SELECT asc, desc, sort FROM sort;
FILTER sort WHERE asc == "desc";
SORT desc DESC FROM sort;
SORT asc FROM desc;''').tokenize()).parse()
    assert program.statements[0].variable == "sort"
    assert program.statements[1].columns == ["asc", "desc", "sort"]
    assert program.statements[3].column_name == "desc"
    assert program.statements[3].ascending is False
    assert program.statements[4].source == "desc"


@pytest.mark.parametrize("source", [
    "SORT FROM sales;", "SORT revenue;", "SORT revenue FROM;",
    "SORT revenue FROM sales", "SORT revenue DOWN FROM sales;",
    "SORT revenue ASC DESC FROM sales;", "SORT revenue, quantity FROM sales;",
    "SORT revenue FROM sales DESC;", "SORT 1 FROM sales;",
])
def test_invalid_sort_syntax(source):
    with pytest.raises(ParseError, match="Syntax error at line 1, column"):
        Parser(Lexer(source).tokenize()).parse()


def test_sort_ast_display(capsys):
    program = Parser(Lexer("SORT revenue DESC FROM sales;").tokenize()).parse()
    print_ast(program)
    assert "SortStmt (column: revenue, order: DESC, from: sales)" in capsys.readouterr().out
