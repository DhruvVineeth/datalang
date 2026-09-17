"""
DataLang Parser Implementation

A recursive descent parser for the DataLang DSL that builds an Abstract Syntax Tree (AST)
from a token stream produced by the Lexer.

Parser Construction Strategy:
1. Each grammar rule becomes a parser method
2. Terminal symbols (tokens) are matched via consume()
3. Non-terminals recursively call their corresponding parse methods
4. Left recursion is eliminated (handled via iteration)
5. Errors are reported with token location information

Grammar Rules Implemented:
(1)  Program        → StatementList
(2-3)  StatementList   → Statement StatementList | Statement
(4-7) Statement      → LoadStmt | SelectStmt | FilterStmt | VisualizeStmt
(8)  LoadStmt        → LOAD STRING_LIT
(9)  SelectStmt       → SELECT ColumnList
(10) FilterStmt       → FILTER ID RELOP Value
(11) PlotStmt         → VISUALIZE ChartType ColumnList
(12-14) ChartType     → BAR | LINE | SCATTER
(15-16) ColumnList    → ID COMMA ColumnList | ID
(17-22) RELOP         → GT | LT | EQ | GE | LE | NEQ
(23-25) Value         → INT_LIT | FLOAT_LIT | STRING_LIT
"""

from dataclasses import dataclass
import sys
from pathlib import Path
from typing import List, Optional, Union

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.lexer.lexer import Token, TokenType, Lexer


# ============================================================================
# ABSTRACT SYNTAX TREE (AST) NODE DEFINITIONS
# ============================================================================
# These classes represent the structure of a parsed DataLang program.
# Each node type corresponds to a grammar rule (non-terminal).

@dataclass
class ASTNode:
    """Base class for all AST nodes. Provides location tracking."""
    line: int
    column: int


@dataclass
class Program(ASTNode):
    """
    Root node of the AST.
    
    Represents Rule (1): Program → StatementList
    
    Attributes:
        statements: List of Statement nodes (LoadStmt, SelectStmt, FilterStmt, or PlotStmt)
    """
    statements: List['Statement']


@dataclass
class LoadStmt(ASTNode):
    """
    Represents Rule (8): LoadStmt → LOAD STRING_LIT
    
    Loads a data source into the system.
    
    Attributes:
        file_path: The string literal representing the file path (e.g., "data.csv")
    """
    file_path: str


@dataclass
class SelectStmt(ASTNode):
    """
    Represents Rule (9): SelectStmt → SELECT ColumnList
    
    Selects specific columns from the data.
    
    Attributes:
        columns: List of column names (identifiers)
    """
    columns: List[str]


@dataclass
class FilterStmt(ASTNode):
    """
    Represents Rule (10): FilterStmt → FILTER ID RELOP Value
    
    Filters data based on a relational expression.
    
    Attributes:
        column_name: The column identifier to filter on
        operator: The relational operator (GT, LT, EQ, GE, LE, NEQ)
        value: The Value node representing the comparison value
    """
    column_name: str
    operator: str  # Operator name (e.g., "GT", "LT", "EQ")
    value: 'Value'


@dataclass
class PlotStmt(ASTNode):
    """
    Represents Rule (11): PlotStmt → PLOT ChartType ColumnList
    
    Visualizes data using a specified chart type.
    
    Attributes:
        chart_type: The chart type (BAR, LINE, or SCATTER)
        columns: List of column names to plot
    """
    chart_type: str  # Chart type name (e.g., "BAR", "LINE", "SCATTER")
    columns: List[str]


@dataclass
class Value(ASTNode):
    """
    Represents Rules (23-25): Value → INT_LIT | FLOAT_LIT | STRING_LIT
    
    A literal value (integer, float, or string).
    
    Attributes:
        type: The value type ("INT", "FLOAT", or "STRING")
        literal: The actual value (int, float, or str)
    """
    type: str  # "INT", "FLOAT", or "STRING"
    literal: Union[int, float, str]


# Type alias for Statement nodes
Statement = Union[LoadStmt, SelectStmt, FilterStmt, PlotStmt]


# ============================================================================
# PARSER CLASS
# ============================================================================

class Parser:
    """
    Recursive descent parser for DataLang.
    
    Construction Strategy:
    - Tokens are provided by the Lexer
    - Parser maintains current position in token stream
    - Each grammar rule has a corresponding parse method
    - Terminals are matched via consume()
    - Non-terminals recursively call their parse methods
    - Errors halt parsing and report location info
    
    Error Handling:
    - ParseError exceptions are raised on syntax errors
    - Error messages include line and column numbers
    - Parser stops at first error (fail-fast approach)
    """
    
    def __init__(self, tokens: List[Token]):
        """
        Initialize the parser with a token stream.
        
        Args:
            tokens: List of Token objects from the Lexer
        """
        self.tokens = tokens
        self.position = 0  # Current position in token stream
    
    def parse(self) -> Program:
        """
        Parse the entire token stream and build an AST.
        
        Entry point that implements Rule (1): Program → StatementList
        
        Returns:
            Program node (root of the AST)
            
        Raises:
            ParseError: If the input is not a valid DataLang program
        """
        statements = self._parse_statement_list()
        
        # Ensure we've consumed all tokens (except EOF)
        if self._current_token().type != TokenType.EOF:
            self._error(f"Unexpected token after program: {self._current_token().lexeme}")
        
        return Program(
            statements=statements,
            line=self.tokens[0].line,
            column=self.tokens[0].column
        )
    
    # ========================================================================
    # Rule (2-3): StatementList → Statement StatementList | Statement
    # ========================================================================
    # This rule is left-recursive in the grammar, but we transform it to use
    # iteration instead (which is more efficient and avoids infinite recursion).
    # The loop continues parsing statements until we reach EOF or an unexpected token.
    
    def _parse_statement_list(self) -> List[Statement]:
        """
        Parse a sequence of statements (Rule 2-3).
        
        Transforms left-recursive rule:
            StatementList → Statement StatementList | Statement
        
        Into iterative form:
            StatementList → (Statement)*
        
        The loop accumulates statements until reaching EOF or an error.
        
        Returns:
            List of Statement nodes (LoadStmt, SelectStmt, FilterStmt, PlotStmt)
        """
        statements = []
        
        # Keep parsing statements while we haven't reached EOF
        while self._current_token().type != TokenType.EOF:
            stmt = self._parse_statement()
            statements.append(stmt)
        
        return statements
    
    # ========================================================================
    # Rules (4-7): Statement → LoadStmt | SelectStmt | FilterStmt | PlotStmt
    # ========================================================================
    # This is a choice rule: we look at the first token (LOAD, SELECT, FILTER, or PLOT)
    # to decide which statement type to parse.
    
    def _parse_statement(self) -> Statement:
        """
        Parse a single statement (Rules 4-7).
        
        Uses the first token as a lookahead to determine which statement type:
        - LOAD → LoadStmt
        - SELECT → SelectStmt
        - FILTER → FilterStmt
        - VISUALIZE → PlotStmt
        
        Returns:
            One of: LoadStmt, SelectStmt, FilterStmt, or PlotStmt
            
        Raises:
            ParseError: If the first token doesn't match any statement keyword
        """
        token_type = self._current_token().type
        
        if token_type == TokenType.LOAD:
            return self._parse_load_stmt()
        elif token_type == TokenType.SELECT:
            return self._parse_select_stmt()
        elif token_type == TokenType.FILTER:
            return self._parse_filter_stmt()
        elif token_type == TokenType.VISUALIZE:
            return self._parse_plot_stmt()
        else:
            self._error(f"Expected statement (LOAD, SELECT, FILTER, or VISUALIZE), got {self._current_token().lexeme}")
    
    # ========================================================================
    # Rule (8): LoadStmt → LOAD STRING_LIT
    # ========================================================================
    
    def _parse_load_stmt(self) -> LoadStmt:
        """
        Parse a LOAD statement (Rule 8).
        
        Syntax: LOAD <file_path_string>
        
        Example:
            LOAD "data.csv"
        
        Returns:
            LoadStmt node with the file path extracted from the string literal
            
        Raises:
            ParseError: If LOAD keyword or STRING_LIT is missing
        """
        line = self._current_token().line
        column = self._current_token().column
        
        # Consume LOAD keyword
        self._consume(TokenType.LOAD, "Expected LOAD keyword")
        
        # Consume string literal and extract its value
        file_path_token = self._consume(TokenType.STRING_LIT, "Expected file path string after LOAD")
        file_path = file_path_token.literal  # The parsed string value (escape sequences already resolved)
        
        return LoadStmt(
            file_path=file_path,
            line=line,
            column=column
        )
    
    # ========================================================================
    # Rule (9): SelectStmt → SELECT ColumnList
    # ========================================================================
    
    def _parse_select_stmt(self) -> SelectStmt:
        """
        Parse a SELECT statement (Rule 9).
        
        Syntax: SELECT <column_1>, <column_2>, ...
        
        Example:
            SELECT revenue, expenses, profit
        
        Returns:
            SelectStmt node with list of column names
            
        Raises:
            ParseError: If SELECT keyword or ColumnList is missing
        """
        line = self._current_token().line
        column = self._current_token().column
        
        # Consume SELECT keyword
        self._consume(TokenType.SELECT, "Expected SELECT keyword")
        
        # Parse comma-separated column list
        columns = self._parse_column_list()
        
        return SelectStmt(
            columns=columns,
            line=line,
            column=column
        )
    
    # ========================================================================
    # Rule (10): FilterStmt → FILTER ID RELOP Value
    # ========================================================================
    
    def _parse_filter_stmt(self) -> FilterStmt:
        """
        Parse a FILTER statement (Rule 10).
        
        Syntax: FILTER <column> <relop> <value>
        
        Example:
            FILTER amount > 100
            FILTER region != "US"
        
        Returns:
            FilterStmt node with column, operator, and value
            
        Raises:
            ParseError: If required components are missing
        """
        line = self._current_token().line
        column_col = self._current_token().column
        
        # Consume FILTER keyword
        self._consume(TokenType.FILTER, "Expected FILTER keyword")
        
        # Consume column identifier
        column_token = self._consume(TokenType.ID, "Expected column identifier after FILTER")
        column_name = column_token.lexeme
        
        # Parse relational operator
        operator = self._parse_relop()
        
        # Parse comparison value
        value = self._parse_value()
        
        return FilterStmt(
            column_name=column_name,
            operator=operator,
            value=value,
            line=line,
            column=column_col
        )
    
    # ========================================================================
    # Rule (11): PlotStmt → PLOT ChartType ColumnList
    # ========================================================================
    
    def _parse_plot_stmt(self) -> PlotStmt:
        """
        Parse a PLOT statement (Rule 11).
        
        Syntax: VISUALIZE <chart_type> <column_1>, <column_2>, ...
        
        Example:
            VISUALIZE BAR revenue, expenses
            VISUALIZE LINE month, sales
        
        Returns:
            PlotStmt node with chart type and column list
            
        Raises:
            ParseError: If required components are missing
        """
        line = self._current_token().line
        column = self._current_token().column
        
        # Consume VISUALIZE keyword
        self._consume(TokenType.VISUALIZE, "Expected VISUALIZE keyword")
        
        # Parse chart type
        chart_type = self._parse_chart_type()
        
        # Parse column list
        columns = self._parse_column_list()
        
        return PlotStmt(
            chart_type=chart_type,
            columns=columns,
            line=line,
            column=column
        )
    
    # ========================================================================
    # Rules (12-14): ChartType → BAR | LINE | SCATTER
    # ========================================================================
    
    def _parse_chart_type(self) -> str:
        """
        Parse a chart type keyword (Rules 12-14).
        
        Valid chart types:
        - BAR: Bar chart
        - LINE: Line chart
        - SCATTER: Scatter plot
        
        Returns:
            String name of the chart type (e.g., "BAR", "LINE", "SCATTER")
            
        Raises:
            ParseError: If current token is not a valid chart type
        """
        token_type = self._current_token().type
        
        if token_type == TokenType.BAR:
            self._advance()
            return "BAR"
        elif token_type == TokenType.LINE:
            self._advance()
            return "LINE"
        elif token_type == TokenType.SCATTER:
            self._advance()
            return "SCATTER"
        else:
            self._error(f"Expected chart type (BAR, LINE, or SCATTER), got {self._current_token().lexeme}")
    
    # ========================================================================
    # Rules (15-16): ColumnList → ID COMMA ColumnList | ID
    # ========================================================================
    # This rule is left-recursive. We transform it to use iteration:
    #   ColumnList → ID (COMMA ID)*
    
    def _parse_column_list(self) -> List[str]:
        """
        Parse a comma-separated list of column names (Rules 15-16).
        
        Transforms left-recursive rule:
            ColumnList → ID COMMA ColumnList | ID
        
        Into iterative form:
            ColumnList → ID (COMMA ID)*
        
        Examples:
            revenue
            revenue, expenses, profit
            month, sales, target
        
        Returns:
            List of column name strings (identifiers)
            
        Raises:
            ParseError: If first ID is missing
        """
        columns = []
        
        # Parse first column (required)
        first_column_token = self._consume(TokenType.ID, "Expected column name")
        columns.append(first_column_token.lexeme)
        
        # Parse additional columns (zero or more)
        # Keep consuming COMMA ID pairs as long as we see a comma
        while self._current_token().type == TokenType.COMMA:
            self._advance()  # Consume COMMA
            column_token = self._consume(TokenType.ID, "Expected column name after comma")
            columns.append(column_token.lexeme)
        
        return columns
    
    # ========================================================================
    # Rules (17-22): RELOP → GT | LT | EQ | GE | LE | NEQ
    # ========================================================================
    
    def _parse_relop(self) -> str:
        """
        Parse a relational operator (Rules 17-22).
        
        Valid operators:
        - GT (>): Greater than
        - LT (<): Less than
        - EQ (==): Equal to
        - GE (>=): Greater than or equal
        - LE (<=): Less than or equal
        - NEQ (!=): Not equal
        
        Returns:
            String name of the operator (e.g., "GT", "LT", "EQ")
            
        Raises:
            ParseError: If current token is not a valid operator
        """
        token_type = self._current_token().type
        
        if token_type == TokenType.GT:
            self._advance()
            return "GT"
        elif token_type == TokenType.LT:
            self._advance()
            return "LT"
        elif token_type == TokenType.EQ:
            self._advance()
            return "EQ"
        elif token_type == TokenType.GE:
            self._advance()
            return "GE"
        elif token_type == TokenType.LE:
            self._advance()
            return "LE"
        elif token_type == TokenType.NEQ:
            self._advance()
            return "NEQ"
        else:
            self._error(f"Expected relational operator (>, <, ==, >=, <=, !=), got {self._current_token().lexeme}")
    
    # ========================================================================
    # Rules (23-25): Value → INT_LIT | FLOAT_LIT | STRING_LIT
    # ========================================================================
    
    def _parse_value(self) -> Value:
        """
        Parse a literal value (Rules 23-25).
        
        Valid value types:
        - INT_LIT: Integer literal (e.g., 42, 100, -5)
        - FLOAT_LIT: Floating point literal (e.g., 3.14, 99.99)
        - STRING_LIT: String literal (e.g., "US", "data.csv")
        
        Returns:
            Value node with type and parsed literal
            
        Raises:
            ParseError: If current token is not a valid value
        """
        token = self._current_token()
        line = token.line
        column = token.column
        
        if token.type == TokenType.INT_LIT:
            self._advance()
            return Value(
                type="INT",
                literal=token.literal,  # Already parsed as int by Lexer
                line=line,
                column=column
            )
        elif token.type == TokenType.FLOAT_LIT:
            self._advance()
            return Value(
                type="FLOAT",
                literal=token.literal,  # Already parsed as float by Lexer
                line=line,
                column=column
            )
        elif token.type == TokenType.STRING_LIT:
            self._advance()
            return Value(
                type="STRING",
                literal=token.literal,  # Already parsed and escape sequences resolved
                line=line,
                column=column
            )
        else:
            self._error(f"Expected value (integer, float, or string), got {token.lexeme}")
    
    # ========================================================================
    # UTILITY METHODS
    # ========================================================================
    
    def _current_token(self) -> Token:
        """
        Get the token at the current position in the stream.
        
        Returns:
            The current Token, or EOF token if at end of stream
        """
        if self.position >= len(self.tokens):
            return self.tokens[-1]  # Return EOF token
        return self.tokens[self.position]
    
    def _advance(self) -> Token:
        """
        Move to the next token in the stream.
        
        Returns:
            The token we just moved past
        """
        token = self._current_token()
        if self.position < len(self.tokens) - 1:
            self.position += 1
        return token
    
    def _consume(self, expected_type: TokenType, error_message: str) -> Token:
        """
        Consume (match and advance past) a token of the expected type.
        
        This is the core operation for matching terminal symbols in the grammar.
        If the current token matches, we advance and return it.
        If not, we raise an error with location information.
        
        Args:
            expected_type: The TokenType we expect to see
            error_message: The error message if the token doesn't match
            
        Returns:
            The matched token (now at the previous position)
            
        Raises:
            ParseError: If current token doesn't match expected_type
        """
        current = self._current_token()
        
        if current.type != expected_type:
            self._error(error_message)
        
        self._advance()
        return current
    
    def _error(self, message: str) -> None:
        """
        Report a parsing error and halt.
        
        Includes location information (line and column) from the current token.
        This implements fail-fast error handling: we stop at the first error
        rather than trying to recover.
        
        Args:
            message: Description of the error
            
        Raises:
            ParseError: Always (terminates parsing)
        """
        token = self._current_token()
        error_msg = f"Parse error at line {token.line}, column {token.column}: {message}"
        raise ParseError(error_msg)


class ParseError(Exception):
    """Exception raised when the parser encounters a syntax error."""
    pass


# ============================================================================
# PRETTY-PRINTING THE AST
# ============================================================================

def print_ast(node: ASTNode, indent: int = 0) -> None:
    """
    Pretty-print an AST node and its children.
    
    Used for debugging and visualization of the parse tree.
    
    Args:
        node: The AST node to print
        indent: Current indentation level (for nested nodes)
    """
    prefix = "  " * indent
    
    if isinstance(node, Program):
        print(f"{prefix}Program")
        for stmt in node.statements:
            print_ast(stmt, indent + 1)
    
    elif isinstance(node, LoadStmt):
        print(f"{prefix}LoadStmt (file: {node.file_path})")
    
    elif isinstance(node, SelectStmt):
        print(f"{prefix}SelectStmt (columns: {', '.join(node.columns)})")
    
    elif isinstance(node, FilterStmt):
        print(f"{prefix}FilterStmt")
        print(f"{prefix}  column: {node.column_name}")
        print(f"{prefix}  operator: {node.operator}")
        print(f"{prefix}  value:")
        print_ast(node.value, indent + 2)
    
    elif isinstance(node, PlotStmt):
        print(f"{prefix}PlotStmt (chart: {node.chart_type})")
        print(f"{prefix}  columns: {', '.join(node.columns)}")
    
    elif isinstance(node, Value):
        print(f"{prefix}Value ({node.type}: {node.literal})")


def main():
    """
    Example usage: tokenize sample code and parse it.
    """
    # Sample DataLang program
    source = '''LOAD "sales_data.csv"
SELECT revenue, expenses, profit
FILTER revenue > 1000
VISUALIZE BAR revenue, expenses'''
    
    print("=" * 70)
    print("DATALANG PARSER EXAMPLE")
    print("=" * 70)
    print("\nSource Code:")
    print(source)
    print("\n" + "=" * 70)
    
    # Tokenize
    print("\nTokenization:")
    lexer = Lexer(source)
    tokens = lexer.tokenize()
    
    non_eof_tokens = [t for t in tokens if t.type != TokenType.EOF]
    print(f"Generated {len(non_eof_tokens)} tokens:")
    for i, token in enumerate(non_eof_tokens[:15]):  # Show first 15
        print(f"  {i:2d}: {token.type.name:12} = {token.lexeme:20}")
    if len(non_eof_tokens) > 15:
        print(f"  ... and {len(non_eof_tokens) - 15} more tokens")
    
    # Parse
    print("\n" + "=" * 70)
    print("Parsing:")
    try:
        parser = Parser(tokens)
        ast = parser.parse()
        
        print("\nAST (Abstract Syntax Tree):")
        print_ast(ast)
        print("\n✓ Parsing successful!")
    
    except ParseError as e:
        print(f"\n✗ Parsing failed: {e}")


if __name__ == "__main__":
    main()
