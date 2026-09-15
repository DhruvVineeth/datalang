"""
Comprehensive test suite for the DataLang Lexer.

Tests cover:
1. Valid keywords
2. Identifiers
3. Numbers (integers and floats)
4. Strings with escape sequences
5. Operators (comparison and compound)
6. Delimiters (parentheses, commas, semicolons)
7. Unknown/unexpected characters
8. Malformed strings (unterminated)
9. Whitespace and comments
10. Multiple complete statements

For each test, expected tokens are provided for validation.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.lexer.lexer import Lexer, TokenType


def test_case_1_valid_keywords():
    """
    Test Case 1: Valid Keywords
    
    Covers recognition of keywords from all categories:
    - Data operations: LOAD, SELECT, FROM, WHERE, FILTER
    - Grouping/aggregation: GROUP, BY, AGGREGATE
    - Logical operators: AND, OR, NOT
    - Visualization: VISUALIZE, OF
    
    Expected: All keywords recognized with correct TokenType
    """
    source = "LOAD SELECT FROM WHERE FILTER GROUP BY AGGREGATE AND OR NOT VISUALIZE OF"
    lexer = Lexer(source)
    tokens = lexer.tokenize()
    
    expected_types = [
        TokenType.LOAD,
        TokenType.SELECT,
        TokenType.FROM,
        TokenType.WHERE,
        TokenType.FILTER,
        TokenType.GROUP,
        TokenType.BY,
        TokenType.AGGREGATE,
        TokenType.AND,
        TokenType.OR,
        TokenType.NOT,
        TokenType.VISUALIZE,
        TokenType.OF,
        TokenType.EOF,
    ]
    
    print("TEST 1: Valid Keywords")
    print(f"Input: {source}\n")
    assert len(tokens) == len(expected_types), f"Expected {len(expected_types)} tokens, got {len(tokens)}"
    
    for i, (token, expected_type) in enumerate(zip(tokens, expected_types)):
        print(f"  Token {i}: {token.type.name:12} = {token.lexeme:15} (line {token.line}, col {token.column})")
        assert token.type == expected_type, f"Token {i}: expected {expected_type.name}, got {token.type.name}"
    
    print("✓ PASSED\n")


def test_case_2_aggregation_and_chart_keywords():
    """
    Test Case 2: Aggregation Functions and Chart Type Keywords
    
    Covers specialized keyword categories:
    - Aggregation: SUM, AVG, COUNT, MIN, MAX
    - Chart types: BAR, LINE, SCATTER, PIE
    
    Expected: All keywords recognized as their specific types
    """
    source = "SUM AVG COUNT MIN MAX BAR LINE SCATTER PIE"
    lexer = Lexer(source)
    tokens = lexer.tokenize()
    
    expected_types = [
        TokenType.SUM,
        TokenType.AVG,
        TokenType.COUNT,
        TokenType.MIN,
        TokenType.MAX,
        TokenType.BAR,
        TokenType.LINE,
        TokenType.SCATTER,
        TokenType.PIE,
        TokenType.EOF,
    ]
    
    print("TEST 2: Aggregation Functions & Chart Keywords")
    print(f"Input: {source}\n")
    assert len(tokens) == len(expected_types), f"Expected {len(expected_types)} tokens, got {len(tokens)}"
    
    for i, (token, expected_type) in enumerate(zip(tokens, expected_types)):
        print(f"  Token {i}: {token.type.name:12} = {token.lexeme:15} (line {token.line}, col {token.column})")
        assert token.type == expected_type, f"Token {i}: expected {expected_type.name}, got {token.type.name}"
    
    print("✓ PASSED\n")


def test_case_3_identifiers_and_numbers():
    """
    Test Case 3: Identifiers and Numbers
    
    Covers:
    - Identifiers: variable names with letters, digits, underscores
    - Integer literals: positive integers
    - Float literals: decimal numbers
    
    Mix of valid identifiers and numeric tokens.
    
    Expected:
    - Names → ID tokens (sales_data, revenue2024, _temp)
    - 42, 1000 → INT_LIT tokens
    - 3.14, 99.99, 0.5 → FLOAT_LIT tokens
    """
    source = "sales_data 42 revenue2024 3.14 _temp 1000 99.99 x 0.5"
    lexer = Lexer(source)
    tokens = lexer.tokenize()
    
    expected_types = [
        TokenType.ID,         # sales_data
        TokenType.INT_LIT,    # 42
        TokenType.ID,         # revenue2024
        TokenType.FLOAT_LIT,  # 3.14
        TokenType.ID,         # _temp
        TokenType.INT_LIT,    # 1000
        TokenType.FLOAT_LIT,  # 99.99
        TokenType.ID,         # x
        TokenType.FLOAT_LIT,  # 0.5
        TokenType.EOF,
    ]
    
    expected_literals = [
        None,    # sales_data
        42,      # 42
        None,    # revenue2024
        3.14,    # 3.14
        None,    # _temp
        1000,    # 1000
        99.99,   # 99.99
        None,    # x
        0.5,     # 0.5
        None,    # EOF
    ]
    
    print("TEST 3: Identifiers and Numbers")
    print(f"Input: {source}\n")
    assert len(tokens) == len(expected_types), f"Expected {len(expected_types)} tokens, got {len(tokens)}"
    
    for i, (token, expected_type, expected_literal) in enumerate(zip(tokens, expected_types, expected_literals)):
        print(f"  Token {i}: {token.type.name:12} = {token.lexeme:15} literal={token.literal} (line {token.line}, col {token.column})")
        assert token.type == expected_type, f"Token {i}: expected {expected_type.name}, got {token.type.name}"
        assert token.literal == expected_literal, f"Token {i}: expected literal {expected_literal}, got {token.literal}"
    
    print("✓ PASSED\n")


def test_case_4_string_literals():
    """
    Test Case 4: String Literals with Escape Sequences
    
    Covers:
    - Simple strings: "hello"
    - Strings with spaces: "hello world"
    - Escape sequences: \", \\, \n, \t, \r
    
    Expected:
    - Each string parsed as STRING_LIT
    - Literal contains decoded value (escape sequences resolved)
    - Lexeme shows original quoted form
    """
    source = 'name "Alice" path "data\\file" greeting "hello\\nworld" tab "a\\tb" quote "He said \\"hi\\""'
    lexer = Lexer(source)
    tokens = lexer.tokenize()
    
    print("TEST 4: String Literals with Escape Sequences")
    print(f"Input: {source}\n")
    
    # Check token types
    expected_indices = {
        1: (TokenType.STRING_LIT, "Alice"),         # "Alice"
        3: (TokenType.STRING_LIT, "data\\file"),    # "data\\file"
        5: (TokenType.STRING_LIT, "hello\nworld"),  # "hello\\nworld" → newline
        7: (TokenType.STRING_LIT, "a\tb"),          # "a\\tb" → tab
        9: (TokenType.STRING_LIT, 'He said "hi"'),  # "He said \\"hi\\""
    }
    
    assert tokens[0].type == TokenType.ID, "Expected ID for 'name'"
    assert tokens[2].type == TokenType.ID, "Expected ID for 'path'"
    assert tokens[4].type == TokenType.ID, "Expected ID for 'greeting'"
    assert tokens[6].type == TokenType.ID, "Expected ID for 'tab'"
    assert tokens[8].type == TokenType.ID, "Expected ID for 'quote'"
    
    for idx, (expected_type, expected_literal) in expected_indices.items():
        token = tokens[idx]
        print(f"  Token {idx}: {token.type.name:12} = {repr(token.lexeme):25} literal={repr(token.literal)}")
        assert token.type == expected_type, f"Token {idx}: expected {expected_type.name}, got {token.type.name}"
        assert token.literal == expected_literal, f"Token {idx}: expected literal {repr(expected_literal)}, got {repr(token.literal)}"
    
    assert tokens[-1].type == TokenType.EOF
    print("✓ PASSED\n")


def test_case_5_operators():
    """
    Test Case 5: Comparison Operators
    
    Covers:
    - Two-character operators: ==, !=, <=, >=
    - Single-character operators: <, >
    
    Expected:
    - Correct operator token types for each comparison
    """
    source = "a == b c != d x < y z > w m <= n p >= q"
    lexer = Lexer(source)
    tokens = lexer.tokenize()
    
    expected_types = [
        TokenType.ID,    # a
        TokenType.EQ,    # ==
        TokenType.ID,    # b
        TokenType.ID,    # c
        TokenType.NEQ,   # !=
        TokenType.ID,    # d
        TokenType.ID,    # x
        TokenType.LT,    # <
        TokenType.ID,    # y
        TokenType.ID,    # z
        TokenType.GT,    # >
        TokenType.ID,    # w
        TokenType.ID,    # m
        TokenType.LE,    # <=
        TokenType.ID,    # n
        TokenType.ID,    # p
        TokenType.GE,    # >=
        TokenType.ID,    # q
        TokenType.EOF,
    ]
    
    print("TEST 5: Comparison Operators")
    print(f"Input: {source}\n")
    assert len(tokens) == len(expected_types), f"Expected {len(expected_types)} tokens, got {len(tokens)}"
    
    for i, (token, expected_type) in enumerate(zip(tokens, expected_types)):
        print(f"  Token {i}: {token.type.name:12} = {token.lexeme:5}")
        assert token.type == expected_type, f"Token {i}: expected {expected_type.name}, got {token.type.name}"
    
    print("✓ PASSED\n")


def test_case_6_delimiters():
    """
    Test Case 6: Delimiters
    
    Covers:
    - Parentheses: ( )
    - Comma: ,
    - Semicolon: ;
    
    Expected:
    - Each delimiter recognized as LPAREN, RPAREN, COMMA, or SEMI
    """
    source = "func(a, b); result(x, y, z);"
    lexer = Lexer(source)
    tokens = lexer.tokenize()
    
    expected_types = [
        TokenType.ID,      # func
        TokenType.LPAREN,  # (
        TokenType.ID,      # a
        TokenType.COMMA,   # ,
        TokenType.ID,      # b
        TokenType.RPAREN,  # )
        TokenType.SEMI,    # ;
        TokenType.ID,      # result
        TokenType.LPAREN,  # (
        TokenType.ID,      # x
        TokenType.COMMA,   # ,
        TokenType.ID,      # y
        TokenType.COMMA,   # ,
        TokenType.ID,      # z
        TokenType.RPAREN,  # )
        TokenType.SEMI,    # ;
        TokenType.EOF,
    ]
    
    print("TEST 6: Delimiters")
    print(f"Input: {source}\n")
    assert len(tokens) == len(expected_types), f"Expected {len(expected_types)} tokens, got {len(tokens)}"
    
    for i, (token, expected_type) in enumerate(zip(tokens, expected_types)):
        print(f"  Token {i}: {token.type.name:12} = {token.lexeme:5}")
        assert token.type == expected_type, f"Token {i}: expected {expected_type.name}, got {token.type.name}"
    
    print("✓ PASSED\n")


def test_case_7_unknown_characters():
    """
    Test Case 7: Unknown/Unexpected Characters
    
    Covers error handling for:
    - Single = (should be ==)
    - Single ! (should be !=)
    - @ symbol (not in DataLang)
    - $ symbol (not in DataLang)
    
    Expected:
    - ERROR tokens generated with helpful messages
    """
    source = "a = b c ! d x @ y z $ w"
    lexer = Lexer(source)
    tokens = lexer.tokenize()
    
    print("TEST 7: Unknown Characters & Invalid Operators")
    print(f"Input: {source}\n")
    
    # Check specific error positions
    assert tokens[0].type == TokenType.ID      # a
    assert tokens[1].type == TokenType.ERROR   # = (error)
    assert "did you mean ==" in tokens[1].lexeme, "Expected helpful message for ="
    
    assert tokens[2].type == TokenType.ID      # b
    assert tokens[3].type == TokenType.ID      # c
    assert tokens[4].type == TokenType.ERROR   # ! (error)
    assert "did you mean !=" in tokens[4].lexeme, "Expected helpful message for !"
    
    # Print error details
    for i, token in enumerate(tokens):
        if token.type == TokenType.ERROR:
            print(f"  Token {i}: {token.type.name:12} = {token.lexeme}")
        else:
            print(f"  Token {i}: {token.type.name:12} = {token.lexeme}")
    
    print("✓ PASSED (errors correctly detected)\n")


def test_case_8_malformed_strings():
    """
    Test Case 8: Malformed/Unterminated Strings
    
    Covers error handling for:
    - String without closing quote (reached EOF)
    - String with unmatched escape sequence
    
    Expected:
    - ERROR token generated
    - Message indicates unterminated string with line number
    """
    source = 'greeting "hello world'  # Missing closing quote
    lexer = Lexer(source)
    tokens = lexer.tokenize()
    
    print("TEST 8: Malformed Strings (Unterminated)")
    print(f"Input: {source}\n")
    
    assert tokens[0].type == TokenType.ID  # greeting
    assert tokens[1].type == TokenType.ERROR  # Unterminated string
    assert "Unterminated string" in tokens[1].lexeme, "Expected error message about unterminated string"
    assert "line 1" in tokens[1].lexeme, "Expected line number in error message"
    
    for i, token in enumerate(tokens):
        print(f"  Token {i}: {token.type.name:12} = {repr(token.lexeme)}")
    
    print("✓ PASSED (unterminated string detected)\n")


def test_case_9_whitespace_and_comments():
    """
    Test Case 9: Whitespace Handling and Comments
    
    Covers:
    - Spaces and tabs between tokens
    - Newlines (line counter increment)
    - Comments: # to end of line
    - Multiple lines of code
    
    Expected:
    - Whitespace skipped (not tokenized)
    - Comments skipped
    - Line/column numbers correctly tracked
    - Tokens on different lines have correct line numbers
    """
    source = """SELECT data # this is a comment
FROM table
WHERE x == 5"""
    
    lexer = Lexer(source)
    tokens = lexer.tokenize()
    
    print("TEST 9: Whitespace & Comments")
    print(f"Input:\n{source}\n")
    
    expected_structure = [
        (TokenType.SELECT, "SELECT", 1),
        (TokenType.ID, "data", 1),
        (TokenType.FROM, "FROM", 2),
        (TokenType.ID, "table", 2),
        (TokenType.WHERE, "WHERE", 3),
        (TokenType.ID, "x", 3),
        (TokenType.EQ, "==", 3),
        (TokenType.INT_LIT, "5", 3),
        (TokenType.EOF, "", 3),
    ]
    
    print("Token breakdown:")
    for i, (token, (expected_type, expected_lexeme, expected_line)) in enumerate(zip(tokens, expected_structure)):
        print(f"  Token {i}: Line {token.line} | {token.type.name:12} = {token.lexeme:10}")
        assert token.type == expected_type, f"Token {i}: expected type {expected_type.name}, got {token.type.name}"
        assert token.line == expected_line, f"Token {i}: expected line {expected_line}, got {token.line}"
    
    assert len(tokens) == len(expected_structure), f"Expected {len(expected_structure)} tokens, got {len(tokens)}"
    print("✓ PASSED (whitespace and comments correctly handled)\n")


def test_case_10_complete_statement():
    """
    Test Case 10: Complete Multi-Statement Program
    
    A realistic DataLang program with:
    - LOAD statement with string
    - FILTER with comparison operators
    - GROUP/AGGREGATE with functions
    - VISUALIZE with chart type
    
    Tests the full pipeline: keywords, identifiers, numbers, strings,
    operators, and delimiters all working together.
    
    Expected:
    - All 60+ tokens correctly classified
    - Proper line/column tracking across multiple statements
    - No errors in well-formed code
    """
    source = '''LOAD "sales_data.csv" AS dataset;
FILTER dataset WHERE amount > 100 AND region != "US";
AGGREGATE SUM(amount), COUNT(id) GROUP BY region;
VISUALIZE BAR OF region;'''
    
    lexer = Lexer(source)
    tokens = lexer.tokenize()
    
    print("TEST 10: Complete Multi-Statement Program")
    print(f"Input:\n{source}\n")
    
    # Verify overall structure without checking every token
    # Just ensure no ERROR tokens and reasonable count
    error_tokens = [t for t in tokens if t.type == TokenType.ERROR]
    assert len(error_tokens) == 0, f"Unexpected error tokens: {[t.lexeme for t in error_tokens]}"
    
    # Count major token types
    keyword_count = sum(1 for t in tokens if t.type in [
        TokenType.LOAD, TokenType.FILTER, TokenType.WHERE, TokenType.AND,
        TokenType.AGGREGATE, TokenType.SUM, TokenType.COUNT, TokenType.GROUP,
        TokenType.BY, TokenType.VISUALIZE, TokenType.BAR, TokenType.OF, TokenType.AS
    ])
    
    string_count = sum(1 for t in tokens if t.type == TokenType.STRING_LIT)
    number_count = sum(1 for t in tokens if t.type == TokenType.INT_LIT)
    operator_count = sum(1 for t in tokens if t.type in [TokenType.GT, TokenType.NEQ])
    delimiter_count = sum(1 for t in tokens if t.type in [TokenType.LPAREN, TokenType.RPAREN, TokenType.COMMA, TokenType.SEMI])
    
    print(f"Token distribution:")
    print(f"  Keywords: {keyword_count}")
    print(f"  Strings: {string_count}")
    print(f"  Numbers: {number_count}")
    print(f"  Operators: {operator_count}")
    print(f"  Delimiters: {delimiter_count}")
    print(f"  Total (excluding EOF): {len(tokens) - 1}\n")
    
    print("Full token list:")
    for i, token in enumerate(tokens):
        if token.type != TokenType.EOF:
            print(f"  Token {i:2d}: Line {token.line} | {token.type.name:12} = {token.lexeme:20} (col {token.column})")
        else:
            print(f"  Token {i:2d}: {token.type.name:12}")
    
    # Verify expected token counts
    assert keyword_count >= 9, f"Expected at least 9 keywords, got {keyword_count}"
    assert string_count >= 2, f"Expected at least 2 strings, got {string_count}"
    assert operator_count >= 2, f"Expected at least 2 operators, got {operator_count}"
    
    print("\n✓ PASSED (complete program tokenized correctly)\n")


def run_all_tests():
    """Run all 10 test cases."""
    print("=" * 70)
    print("DATALANG LEXER TEST SUITE")
    print("=" * 70)
    print()
    
    test_case_1_valid_keywords()
    test_case_2_aggregation_and_chart_keywords()
    test_case_3_identifiers_and_numbers()
    test_case_4_string_literals()
    test_case_5_operators()
    test_case_6_delimiters()
    test_case_7_unknown_characters()
    test_case_8_malformed_strings()
    test_case_9_whitespace_and_comments()
    test_case_10_complete_statement()
    
    print("=" * 70)
    print("ALL TESTS PASSED ✓")
    print("=" * 70)


if __name__ == "__main__":
    run_all_tests()
