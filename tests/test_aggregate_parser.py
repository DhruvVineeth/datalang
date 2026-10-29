"""Syntax and AST contracts; these tests never execute a dataset."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.ast import AggregateStmt
from src.lexer.lexer import Lexer, TokenType
from src.parser.parser import ParseError, Parser, print_ast


@pytest.mark.parametrize("function", ["SUM", "AVG", "COUNT", "MIN", "MAX"])
@pytest.mark.parametrize("group_by", [None, "product"])
def test_aggregate_ast(function, group_by):
    grouping = f" GROUP BY {group_by}" if group_by else ""
    source = f"\n  aggregate {function.lower()}(Revenue) from sales{grouping};"
    statement = Parser(Lexer(source).tokenize()).parse().statements[0]
    assert isinstance(statement, AggregateStmt)
    assert (statement.function, statement.column_name, statement.source) == (function, "Revenue", "sales")
    assert statement.group_by == group_by
    assert (statement.line, statement.column) == (2, 2)


@pytest.mark.parametrize("source", [
    "AGGREGATE SUM revenue FROM sales;",
    "AGGREGATE SUM() FROM sales;",
    "AGGREGATE MEDIAN(revenue) FROM sales;",
    "AGGREGATE SUM(revenue) sales;",
    "AGGREGATE SUM(revenue) FROM sales",
    "AGGREGATE SUM(revenue), AVG(revenue) FROM sales;",
    "AGGREGATE SUM(revenue) FROM sales GROUP product;",
    "AGGREGATE SUM(revenue) FROM sales GROUP BY;",
    "AGGREGATE SUM(revenue) FROM sales GROUP BY product, region;",
    "GROUP BY product FROM sales;",
])
def test_invalid_aggregate_syntax(source):
    with pytest.raises(ParseError, match="Syntax error at line 1, column"):
        Parser(Lexer(source).tokenize()).parse()


def test_count_star_remains_a_lexical_error():
    tokens = Lexer("AGGREGATE COUNT(*) FROM sales;").tokenize()
    assert any(token.type == TokenType.ERROR and "*" in token.lexeme for token in tokens)


def test_aggregate_ast_display(capsys):
    program = Parser(Lexer("AGGREGATE SUM(revenue) FROM sales GROUP BY product;").tokenize()).parse()
    print_ast(program)
    assert "AggregateStmt (SUM(revenue), from: sales, group by: product)" in capsys.readouterr().out
