"""
DataLang Lexer Implementation

A minimal lexer for the DataLang DSL that tokenizes source code into a stream
of tokens. Handles keywords, identifiers, numbers, strings, operators, and
delimiters with comprehensive error reporting.
"""

from enum import Enum, auto
from dataclasses import dataclass
from typing import List, Optional


class TokenType(Enum):
    """
    Enumeration of all token types in the DataLang language.
    
    Categories:
    - Keywords: LOAD, AS, FILTER, WHERE, SELECT, FROM, AGGREGATE, GROUP, BY,
                VISUALIZE, OF, AND, OR, NOT, SUM, AVG, COUNT, MIN, MAX,
                BAR, LINE, SCATTER, PIE
    - Literals: ID, STRING_LIT, INT_LIT, FLOAT_LIT
    - Operators: EQ, NEQ, LT, GT, LE, GE
    - Delimiters: SEMI, COMMA, LPAREN, RPAREN
    - Special: EOF (end of file), ERROR (lexical error)
    """
    # Keywords
    LOAD = auto()
    AS = auto()
    FILTER = auto()
    WHERE = auto()
    SELECT = auto()
    FROM = auto()
    AGGREGATE = auto()
    GROUP = auto()
    BY = auto()
    VISUALIZE = auto()
    OF = auto()
    AND = auto()
    OR = auto()
    NOT = auto()
    
    # Aggregation functions
    SUM = auto()
    AVG = auto()
    COUNT = auto()
    MIN = auto()
    MAX = auto()
    
    # Chart types
    BAR = auto()
    LINE = auto()
    SCATTER = auto()
    PIE = auto()
    
    # Literals
    ID = auto()
    STRING_LIT = auto()
    INT_LIT = auto()
    FLOAT_LIT = auto()
    
    # Operators
    EQ = auto()      # ==
    NEQ = auto()     # !=
    LT = auto()      # <
    GT = auto()      # >
    LE = auto()      # <=
    GE = auto()      # >=
    
    # Delimiters
    SEMI = auto()    # ;
    COMMA = auto()   # ,
    LPAREN = auto()  # (
    RPAREN = auto()  # )
    
    # Special
    EOF = auto()
    ERROR = auto()


@dataclass
class Token:
    """
    Represents a single token in the source code.
    
    Attributes:
        type: The TokenType of this token
        lexeme: The raw text from the source code
        literal: The parsed value (for numbers/strings), None for others
        line: Line number where the token appears (1-indexed)
        column: Column number where the token appears (0-indexed)
    """
    type: TokenType
    lexeme: str
    literal: Optional[object]
    line: int
    column: int
    
    def __repr__(self) -> str:
        """Pretty-print token information for debugging."""
        return f"Token({self.type.name:12} {self.lexeme:15} line={self.line} col={self.column})"


class Lexer:
    """
    Tokenizes DataLang source code into a stream of tokens.
    
    The lexer scans the input character by character, building tokens by:
    1. Skipping whitespace and comments
    2. Identifying multi-character operators (==, !=, <=, >=)
    3. Recognizing keywords (case-insensitive)
    4. Parsing identifiers, numbers (int/float), and strings
    5. Identifying single-character delimiters and operators
    6. Reporting lexical errors with precise location information
    """
    
    def __init__(self, source: str):
        """
        Initialize the lexer with source code.
        
        Args:
            source: The DataLang source code to tokenize
        """
        self.source = source
        self.position = 0  # Current character index in source
        self.line = 1      # Current line number (1-indexed)
        self.column = 0    # Current column number (0-indexed)
        self.tokens: List[Token] = []  # Accumulated tokens
        
        # Keywords mapping: maps lowercase keywords to their token types
        self.keywords = {
            'load': TokenType.LOAD,
            'as': TokenType.AS,
            'filter': TokenType.FILTER,
            'where': TokenType.WHERE,
            'select': TokenType.SELECT,
            'from': TokenType.FROM,
            'aggregate': TokenType.AGGREGATE,
            'group': TokenType.GROUP,
            'by': TokenType.BY,
            'visualize': TokenType.VISUALIZE,
            'of': TokenType.OF,
            'and': TokenType.AND,
            'or': TokenType.OR,
            'not': TokenType.NOT,
            'sum': TokenType.SUM,
            'avg': TokenType.AVG,
            'count': TokenType.COUNT,
            'min': TokenType.MIN,
            'max': TokenType.MAX,
            'bar': TokenType.BAR,
            'line': TokenType.LINE,
            'scatter': TokenType.SCATTER,
            'pie': TokenType.PIE,
        }
    
    def tokenize(self) -> List[Token]:
        """
        Scan the entire source code and return all tokens.
        
        Processes the source character by character, delegating to specialized
        methods for different token types. Automatically appends EOF token at end.
        
        Returns:
            List of Token objects, including an EOF token at the end
        """
        while not self._is_at_end():
            self._scan_token()
        
        self._add_token(TokenType.EOF, '')
        return self.tokens
    
    def _scan_token(self) -> None:
        """
        Scan and classify a single token.
        
        Processes whitespace, comments, operators, delimiters, and literals.
        Dispatches to specialized methods based on the current character.
        """
        # Skip whitespace and newlines
        if self._skip_whitespace_and_comments():
            return
        
        # Check for end of file
        if self._is_at_end():
            return
        
        current = self._current_char()
        
        # Two-character operators: ==, !=, <=, >=
        if current in '=!<>':
            self._scan_operator()
        # String literals (double quotes)
        elif current == '"':
            self._scan_string()
        # Numbers (int or float)
        elif current.isdigit():
            self._scan_number()
        # Identifiers and keywords (letters or underscore)
        elif current.isalpha() or current == '_':
            self._scan_identifier()
        # Single-character delimiters and remaining operators
        else:
            self._scan_delimiter()
    
    def _skip_whitespace_and_comments(self) -> bool:
        """
        Skip whitespace and comments, updating line/column accordingly.
        
        Comments start with '#' and extend to end of line.
        Updates line and column counters correctly when newlines are encountered.
        
        Returns:
            True if whitespace/comment was skipped, False if at non-whitespace
        """
        while not self._is_at_end():
            current = self._current_char()
            
            # Skip line comment
            if current == '#':
                # Skip entire comment line
                while not self._is_at_end() and self._current_char() != '\n':
                    self._advance()
                continue
            
            # Skip whitespace
            if current == ' ' or current == '\t' or current == '\r':
                self._advance()
                continue
            
            # Handle newline: increment line counter, reset column
            if current == '\n':
                self.line += 1
                self.column = 0
                self._advance()
                continue
            
            # Found non-whitespace, non-comment character
            return False
        
        return True
    
    def _scan_operator(self) -> None:
        """
        Scan two-character operators: ==, !=, <=, >=
        
        Also handles single-character comparison operators: <, >, =, !
        Checks if the current character forms a two-char operator with the next.
        If not, reports appropriate errors or single-char tokens.
        """
        current = self._current_char()
        self._advance()
        
        # Check if next character forms a two-character operator
        if not self._is_at_end() and self._current_char() == '=':
            self._advance()
            if current == '=':
                self._add_token(TokenType.EQ, '==')
            elif current == '!':
                self._add_token(TokenType.NEQ, '!=')
            elif current == '<':
                self._add_token(TokenType.LE, '<=')
            elif current == '>':
                self._add_token(TokenType.GE, '>=')
        else:
            # Single-character operator or error
            if current == '<':
                self._add_token(TokenType.LT, '<')
            elif current == '>':
                self._add_token(TokenType.GT, '>')
            elif current == '=':
                # Single '=' is not valid in DataLang (use == for comparison)
                self._add_error_token('Unexpected character: = (did you mean ==?)')
            elif current == '!':
                # Single '!' is not valid in DataLang (must be !=)
                self._add_error_token('Unexpected character: ! (did you mean !=?)')
    
    def _scan_string(self) -> None:
        """
        Scan a string literal enclosed in double quotes.
        
        Handles escape sequences: \\", \\\\, \\n, \\t, \\r
        Reports an error if string is not properly closed before EOF.
        The string value is stored in the token's literal field with escape sequences processed.
        """
        start_line = self.line
        start_col = self.column
        self._advance()  # Skip opening quote
        
        value = ''
        
        while not self._is_at_end() and self._current_char() != '"':
            if self._current_char() == '\\':
                # Handle escape sequences
                self._advance()
                if self._is_at_end():
                    break
                
                escape_char = self._current_char()
                if escape_char == '"':
                    value += '"'
                elif escape_char == '\\':
                    value += '\\'
                elif escape_char == 'n':
                    value += '\n'
                elif escape_char == 't':
                    value += '\t'
                elif escape_char == 'r':
                    value += '\r'
                else:
                    # Unknown escape sequence: include backslash and character
                    value += '\\' + escape_char
                
                self._advance()
            else:
                value += self._current_char()
                self._advance()
        
        if self._is_at_end():
            # String was not closed
            self.tokens.append(Token(
                TokenType.ERROR,
                self.source[self.position - (self.column - start_col):self.position],
                None,
                start_line,
                start_col
            ))
            self.tokens[-1].lexeme = f'Unterminated string (started at line {start_line})'
            return
        
        # Skip closing quote
        self._advance()
        
        self._add_token(TokenType.STRING_LIT, f'"{value}"', value)
    
    def _scan_number(self) -> None:
        """
        Scan numeric literals: integers or floats.
        
        Identifies:
        - INT_LIT: sequences of digits (e.g., 42, 0, 999)
        - FLOAT_LIT: digits with decimal point (e.g., 3.14, 0.5)
        
        Stores the parsed numeric value in the token's literal field.
        """
        start_pos = self.position
        
        # Consume all leading digits
        while not self._is_at_end() and self._current_char().isdigit():
            self._advance()
        
        # Check for decimal point (float literal)
        if not self._is_at_end() and self._current_char() == '.' and \
           self.position + 1 < len(self.source) and self.source[self.position + 1].isdigit():
            # This is a float
            self._advance()  # Skip decimal point
            
            # Consume fractional digits
            while not self._is_at_end() and self._current_char().isdigit():
                self._advance()
            
            lexeme = self.source[start_pos:self.position]
            self._add_token(TokenType.FLOAT_LIT, lexeme, float(lexeme))
        else:
            # This is an integer
            lexeme = self.source[start_pos:self.position]
            self._add_token(TokenType.INT_LIT, lexeme, int(lexeme))
    
    def _scan_identifier(self) -> None:
        """
        Scan identifiers and keywords.
        
        Identifiers consist of letters, digits, and underscores, and must start
        with a letter or underscore. Keywords are case-insensitive.
        
        Dispatches to keyword checking to classify the token as either a keyword
        or a generic identifier (ID token).
        """
        start_pos = self.position
        
        # Consume identifier characters (letters, digits, underscores)
        while not self._is_at_end() and (self._current_char().isalnum() or self._current_char() == '_'):
            self._advance()
        
        lexeme = self.source[start_pos:self.position]
        
        # Check if it's a keyword (case-insensitive)
        lower_lexeme = lexeme.lower()
        token_type = self.keywords.get(lower_lexeme, TokenType.ID)
        
        self._add_token(token_type, lexeme)
    
    def _scan_delimiter(self) -> None:
        """
        Scan single-character delimiters and report unexpected characters.
        
        Recognizes: ; , ( )
        
        Any other character is reported as a lexical error with a helpful message.
        """
        current = self._current_char()
        
        if current == ';':
            self._add_token(TokenType.SEMI, ';')
        elif current == ',':
            self._add_token(TokenType.COMMA, ',')
        elif current == '(':
            self._add_token(TokenType.LPAREN, '(')
        elif current == ')':
            self._add_token(TokenType.RPAREN, ')')
        else:
            # Unexpected character
            self._add_error_token(f'Unexpected character: {current}')
        
        self._advance()
    
    def _current_char(self) -> str:
        """
        Get the character at the current position.
        
        Returns:
            The character at self.position, or empty string if at EOF
        """
        if self._is_at_end():
            return ''
        return self.source[self.position]
    
    def _advance(self) -> None:
        """
        Move to the next character and update position/column tracking.
        
        Note: Newlines are handled separately in _skip_whitespace_and_comments()
        to properly update line numbers.
        """
        if not self._is_at_end():
            self.position += 1
            self.column += 1
    
    def _is_at_end(self) -> bool:
        """
        Check if we've reached the end of the source code.
        
        Returns:
            True if position is at or past the end of source
        """
        return self.position >= len(self.source)
    
    def _add_token(self, token_type: TokenType, lexeme: str, literal: Optional[object] = None) -> None:
        """
        Add a token to the token list.
        
        Records the token type, raw lexeme, optional literal value, and position
        (line and column) for error reporting and source mapping.
        
        Args:
            token_type: The TokenType of this token
            lexeme: The raw text from source code
            literal: The parsed value (numbers/strings) or None
        """
        token = Token(
            type=token_type,
            lexeme=lexeme,
            literal=literal,
            line=self.line,
            column=self.column - len(lexeme)
        )
        self.tokens.append(token)
    
    def _add_error_token(self, message: str) -> None:
        """
        Add an error token with a descriptive message.
        
        Used when the lexer encounters invalid syntax that cannot be tokenized.
        Stores the error message in the token's lexeme field.
        
        Args:
            message: The error message describing the lexical problem
        """
        token = Token(
            type=TokenType.ERROR,
            lexeme=message,
            literal=None,
            line=self.line,
            column=self.column
        )
        self.tokens.append(token)


def print_tokens(tokens: List[Token]) -> None:
    """
    Pretty-print all tokens for debugging and testing.
    
    Displays token type, lexeme, line, and column in an aligned table format.
    
    Args:
        tokens: List of Token objects to display
    """
    print(f"{'Type':<15} {'Lexeme':<20} {'Line':<6} {'Column':<6}")
    print("-" * 50)
    for token in tokens:
        print(f"{token.type.name:<15} {token.lexeme:<20} {token.line:<6} {token.column:<6}")
