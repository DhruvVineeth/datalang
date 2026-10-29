"""Stage-local contracts: lexer, parser, semantic analysis and lowering.

Parser tests consume hand-authored tokens. Semantic and IR tests consume
hand-authored AST nodes; none executes a program or invokes another frontend.
"""

import pytest

from src.ast import AggregateStmt, LoadStmt, Program, SelectStmt, SortStmt
from src.interpreter.ir import IRGenerator
from src.lexer.lexer import Lexer, Token, TokenType
from src.parser.parser import ParseError, Parser
from src.semantic.semantic import SemanticAnalysisError, SemanticAnalyzer
from src.symbol_table.symbol_table import SymbolTable
from spec_oracles import FIXTURES, SCHEMA


def test_lexer_keyword_case_contextual_words_and_identifier_case():
    tokens = Lexer("lOaD AS sort asc desc Team team ==").tokenize()
    assert [token.type.name for token in tokens] == [
        "LOAD", "AS", "ID", "ID", "ID", "ID", "ID", "EQ", "EOF",
    ]
    assert [token.lexeme for token in tokens[2:7]] == ["sort", "asc", "desc", "Team", "team"]


@pytest.mark.parametrize("source,message", [
    ("=", "did you mean =="), ("*", "Unexpected character"),
    ("2orders", "Invalid numeric literal"), ('"unfinished', "Unterminated string"),
])
def test_lexer_rejections_have_specified_stage_and_location(source, message):
    error = Lexer("# comment\n  " + source).tokenize()[0]
    assert error.type is TokenType.ERROR
    assert message in error.lexeme
    assert (error.line, error.column) == (2, 2)


@pytest.mark.parametrize("direction,ascending", [(None, True), ("ASC", True), ("DESC", False)])
def test_parser_sort_accepts_contextual_tokens_and_defaults(direction, ascending):
    lexemes = ["SORT", "Amount"] + ([direction] if direction else []) + ["FROM", "orders", ";", ""]
    kinds = [TokenType.ID, TokenType.ID] + ([TokenType.ID] if direction else []) + [
        TokenType.FROM, TokenType.ID, TokenType.SEMI, TokenType.EOF,
    ]
    tokens = [Token(kind, lexeme, None, 3, index * 10) for index, (kind, lexeme) in enumerate(zip(kinds, lexemes))]
    statement = Parser(tokens).parse().statements[0]
    assert (statement.column_name, statement.source, statement.ascending) == ("Amount", "orders", ascending)
    assert (statement.line, statement.column) == (3, 0)


def test_parser_requires_semicolon_with_no_semantic_or_runtime_dependency():
    tokens = [Token(kind, text, None, 2, column) for kind, text, column in [
        (TokenType.SELECT, "SELECT", 2), (TokenType.ID, "Team", 9),
        (TokenType.FROM, "FROM", 14), (TokenType.ID, "orders", 19), (TokenType.EOF, "", 25),
    ]]
    with pytest.raises(ParseError) as failure:
        Parser(tokens).parse()
    assert (failure.value.stage, failure.value.line, failure.value.column) == ("Syntax", 2, 25)
    assert "Expected ';'" in str(failure.value)


@pytest.mark.parametrize("function,name,result_type", [
    ("SUM", "sum_Amount", "Numeric"), ("AVG", "avg_Amount", "Numeric"),
    ("COUNT", "count_Amount", "Integer"), ("MIN", "min_Amount", "Numeric"),
    ("MAX", "max_Amount", "Numeric"),
])
def test_semantic_grouped_output_schema_from_ast(function, name, result_type):
    program = Program(1, 0, [LoadStmt(1, 0, "orders.csv", "orders"),
                             AggregateStmt(2, 2, function, "Amount", "orders", "Team")])
    symbols = SemanticAnalyzer(FIXTURES).analyze(program)
    dataset = symbols.lookup("orders")
    assert dataset.column_order == ["Team", name]
    assert [(column, dataset.columns[column].data_type) for column in dataset.column_order] == [
        ("Team", "String"), (name, result_type),
    ]


def test_failed_semantic_projection_preserves_schema_for_next_statement():
    program = Program(1, 0, [LoadStmt(1, 0, "orders.csv", "orders"),
                             SelectStmt(2, 2, ["Team", "absent"], "orders"),
                             SelectStmt(3, 2, ["Units"], "orders")])
    analyzer = SemanticAnalyzer(FIXTURES)
    with pytest.raises(SemanticAnalysisError) as failure:
        analyzer.analyze(program)
    assert len(failure.value.errors) == 1
    error = failure.value.errors[0]
    assert "absent" in error.message and (error.line, error.column) == (2, 2)
    assert analyzer.symbol_table.lookup("orders").column_order == ["Units"]
    assert analyzer.symbol_table.lookup_column("orders", "Units").data_type == "Integer"


def test_ir_preserves_order_schema_snapshots_and_source_locations_without_execution():
    load = LoadStmt(1, 0, "orders.csv", "orders")
    aggregate = AggregateStmt(2, 2, "SUM", "Amount", "orders", "Team")
    sort = SortStmt(3, 4, "sum_Amount", "orders", False)
    program = Program(1, 0, [load, aggregate, sort])
    # This stage receives the already-checked metadata required by its contract.
    symbols = SymbolTable()
    symbols.insert_dataset("orders", str(FIXTURES / "orders.csv"), dict(SCHEMA))
    symbols.statement_schemas[id(aggregate)] = {"Team": "String", "sum_Amount": "Numeric"}
    symbols.statement_schemas[id(sort)] = {"Team": "String", "sum_Amount": "Numeric"}
    ir = IRGenerator(symbols).generate(program)
    assert [instruction.op for instruction in ir.instructions] == ["LOAD", "AGGREGATE", "SORT"]
    assert [instruction.output for instruction in ir.instructions] == ["T1", "T2", "T3"]
    assert [(instruction.source_line, instruction.source_column) for instruction in ir.instructions] == [(1, 0), (2, 2), (3, 4)]
    assert (ir.instructions[1].input, ir.instructions[2].input) == ("T1", "T2")
    assert ir.instructions[1].output_schema == {"Team": "String", "sum_Amount": "Numeric"}
    assert ir.instructions[2].column_type == "Numeric" and not ir.instructions[2].ascending
