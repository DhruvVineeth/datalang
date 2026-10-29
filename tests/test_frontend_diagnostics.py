"""Frontend errors retain their stage and exact source coordinates."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.lexer.lexer import Lexer, TokenType
from src.parser.parser import ParseError, Parser


@pytest.mark.parametrize("source,message", [
    ("\n  @", "Unexpected character: @"),
    ("\n  2sales", "Invalid numeric literal"),
    ("\n  12abc", "Invalid numeric literal"),
    ("\n  1.2.3", "Invalid numeric literal"),
    ("\n  1e3", "Invalid numeric literal"),
    ("\n  ²", "Invalid numeric literal"),
    ('\n  "unterminated', "Unterminated string"),
    ('\n  "unterminated\\', "Unterminated string"),
])
def test_lexical_errors_are_located_and_do_not_raise_conversion_errors(source, message):
    tokens = Lexer(source).tokenize()
    error = next(token for token in tokens if token.type == TokenType.ERROR)
    assert message in error.lexeme
    assert (error.line, error.column) == (2, 2)
    assert tokens[-1].type == TokenType.EOF


def test_float_overflow_is_a_lexical_diagnostic():
    error = Lexer("9" * 400 + ".0").tokenize()[0]
    assert error.type == TokenType.ERROR
    assert "out of range" in error.lexeme
    assert len(error.lexeme) < 120


def test_raw_string_lexeme_and_location_survive_decoding():
    source = '# comment\r\n  "a\\nb"\r\n  @'
    string, error, eof = Lexer(source).tokenize()
    assert string.lexeme == '"a\\nb"' and string.literal == "a\nb"
    assert (string.line, string.column) == (2, 2)
    assert (error.line, error.column) == (3, 2)


@pytest.mark.parametrize("source,message,line,column", [
    ('LOAD "data.csv" AS data\nSELECT x FROM data;', "Expected ';'.*got 'SELECT'", 2, 0),
    ("\n  FILTER data WHERE x >;", "Expected a value", 2, 23),
    ("\n  SORT x DOWN FROM data;", "Expected 'FROM'.*got 'DOWN'", 2, 9),
    ("\n  AGGREGATE SUM(x FROM data;", "Expected '\\)'.*got 'FROM'", 2, 18),
    ('LOAD "data.csv" AS data', "Expected ';'.*end of input", 1, 23),
])
def test_syntax_error_fields_and_message(source, message, line, column):
    with pytest.raises(ParseError, match=message) as failure:
        Parser(Lexer(source).tokenize()).parse()
    error = failure.value
    assert (error.stage, error.line, error.column) == ("Syntax", line, column)
    assert f"Syntax error at line {line}, column {column}:" in str(error)


def test_parser_does_not_relabel_lexical_errors_as_syntax_errors():
    with pytest.raises(ParseError) as failure:
        Parser(Lexer("\n  @").tokenize()).parse()
    assert failure.value.stage == "Lexical"
    assert str(failure.value).startswith("Lexical error at line 2, column 2:")


def test_deeply_nested_conditions_produce_a_syntax_diagnostic():
    source = "FILTER data WHERE " + "NOT " * 2000 + "x > 0;"
    with pytest.raises(ParseError, match="nesting is too deep") as failure:
        Parser(Lexer(source).tokenize()).parse()
    assert failure.value.stage == "Syntax" and failure.value.line == 1
