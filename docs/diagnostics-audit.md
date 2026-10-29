# Diagnostic and execution-prevention audit

Verified against the token -> AST -> semantic analysis -> IR -> execution
pipeline. The baseline was 341 passing tests. After this audit, all **435 tests
pass**, including **94 new diagnostic cases** in test_frontend_diagnostics.py
and test_diagnostics.py. Expected diagnostic fragments and coordinates are
specified independently in those tests.

**Stage behavior.**

| Stage | Reported failures | Context and prevention |
| --- | --- | --- |
| Lexical | Illegal characters, lone =/!, unterminated strings, malformed numeric literals and unrepresentable numeric values | Token line/column; all lexical errors reported before parsing |
| Syntax | Missing values/delimiters/keywords, unsupported statement forms, unexpected tokens/EOF, excessive recursive nesting | Offending token location, expected construct and actual token/end of input; semantic analysis and execution prevented |
| Semantic | Unknown datasets/columns, unavailable current-schema fields, ambiguous columns, incompatible types, unsupported charts, inaccessible/invalid CSV schemas, excessive filter-tree depth | Statement or comparison coordinates; CSV failures name the dataset/file; no AST/IR dump or execution after failure |
| IR | Lowering or display failure after semantic validation | IR error with originating statement coordinates where available; executor not constructed |
| Runtime | CSV reads, incompatible runtime values, transformations, backend/display failures and unknown IR instructions | Instruction number/operation and source position; subsequent instructions stop; failed result/binding is not published |

**Findings and changes.**

- Tokens and AST nodes already tracked source positions. IR previously discarded
  them. Every lowered instruction now retains source_line/source_column, and
  ComparePred/NotPred/BoolPred retain their corresponding condition coordinates.
  Optional source metadata does not change existing positional IR constructors,
  logical dataclass equality, or ordinary IR formatting.
- Runtime errors previously reported only instruction context. ExecutionError
  now carries structured line/column fields and appends them to the message.
  A nested predicate's more precise location takes precedence over its enclosing
  statement. Comparison failures identify the column, operator and comparison
  value. Unknown instructions receive the same context as recognized operations.
- IR errors were previously uncaught by the driver. Lowering/display errors now
  return status 1 with an IR diagnostic before execution. IR equality display
  now uses the accepted `==` spelling.
- Digit-prefixed identifiers such as 2sales and malformed decimals no longer
  split into misleading valid tokens. Numeric conversion failures and float
  overflow produce lexical diagnostics. The existing integer/decimal grammar
  is retained; scientific notation is unsupported. String lexemes retain exact
  source spelling while literal values remain decoded.
- ParseError retains message, stage and coordinates. Unexpected-token messages
  name the actual token or EOF. Direct parser callers receiving lexical ERROR
  tokens retain a Lexical classification rather than a Syntax label.
- CSV reader errors, including oversized fields, are caught during schema
  inspection and reported as semantic failures at LOAD. Permission/decoding
  details retain dataset and CSV-path context. Missing CSVs found by eager schema
  inspection remain semantic errors; files lost after compilation fail at runtime.
- Excessive parser nesting and semantic FILTER-tree depth produce located
  diagnostics. Semantic validation occurs before optional AST/IR dumps so debug
  flags do not enter later stages after invalid input.
- Missing/unreadable/non-UTF-8 source files and directory paths return status 1
  with a source-reading diagnostic rather than reaching compilation.

**Source-location contract.** Lines remain one-based and columns zero-based,
matching existing tokens and AST nodes. Tabs count as one source character.
The CRLF, decoded-string and multiline-condition tests check that locations
survive without being recalculated from formatted output. A runtime comparison
diagnostic has this form:

```text
Runtime error: Instruction 2 (FILTER): Cannot compare column 'y' using > to 0: ... (line 4, column 8)
```

The trailing position identifies the failing comparison inside the condition.
Backend-specific error text may vary; tests assert the stage, operation,
relevant message content and source coordinates. Manually constructed IR without
source metadata continues to work and does not invent a source location.

**Exit-code contract.**

| Exit code | Meaning |
| --- | --- |
| 0 | Successful compilation/execution, including valid compile-only mode |
| 1 | Lexical, syntax, semantic, IR, source-read or runtime failure |
| 2 | Missing source argument or invalid command-line arguments |

**Executed tests.**

- 17 frontend cases check lexical classification, malformed numbers, float range,
  raw/decoded strings, precise coordinates, structured parser errors and deep NOT
  nesting. Existing lexer/parser cases also remain passing.
- 77 pipeline/runtime/CLI cases check location propagation through all six
  statement kinds and nested predicates; validation gates under normal, debug
  and compile-only modes; semantic CSV/depth errors; IR failures; runtime
  locations and stopping behavior; source I/O; and actual subprocess exit codes.
- Failure-gate tests replace later stages with functions that raise if called.
  A valid LOAD preceding a later invalid statement must not load runtime data or
  plot anything. Backend-failure tests verify that later LOAD instructions never
  execute and that the last successful table/binding survives.
- Eight real CLI subprocess cases check success, lexical/syntax/semantic/runtime
  failure, missing arguments, invalid arguments and absent source files. Covered
  failures report diagnostics without Python tracebacks. Runtime plotting failure
  uses empty data and does not open a GUI.

```text
python3 -B -m pytest tests/test_frontend_diagnostics.py tests/test_diagnostics.py -q -p no:cacheprovider
python3 -B -m pytest tests -q -p no:cacheprovider
```

The complete regression run passed 435 tests. The targeted source/README
whitespace check also passed. Existing user edits to example programs were kept.
