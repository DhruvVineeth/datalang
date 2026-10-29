# Grouping and aggregation validation

Implemented through lexer -> parser/AST -> semantic analysis -> IR -> executor.
The lexer already recognized the required keywords and was not changed.
Grouping is the optional GROUP BY clause of AGGREGATE, not a standalone grouped
object. Sorting was outside that implementation milestone; its subsequent
implementation is recorded in [sorting validation](phase3-sorting-validation.md).

**Stage changes and focused tests.**

| Stage | Change | Focused tests |
| --- | --- | --- |
| Parser/AST | AggregateStmt, one function/target/source, optional single group key, AST display | test_aggregate_parser.py |
| Semantic/symbol table | Numeric-only reductions except COUNT; dataset/column/name-collision checks; evolving SELECT/aggregate schemas; per-aggregate schema snapshots | test_aggregate_semantic.py |
| IR | AggregateIR lowering with current-table binding and checked output schema; reject unchecked aggregate lowering | test_aggregate_ir.py |
| Execution | Null-aware reductions; first-appearance groups including null keys; typed empty/null outputs; atomic result publication and current runtime bindings | test_aggregate_execution.py |

Invalid semantic input is tested to stop before IR generation or execution.
Compile-only mode is tested to lower aggregates without running them. Runtime
tests compile through semantic analysis before executing IR; defensive tests
alter already-validated IR explicitly to check runtime guards.

**Executed versus expected coverage.** Hand-calculated expected values remain
in [phase3-expected-results.md](phase3-expected-results.md). Tests use literal
expected values, not backend reductions to generate their own expectations.

| Original expectation cases | Actual execution coverage |
| --- | --- |
| N1: ungrouped functions | All five functions on Numeric revenue and Integer quantity; string COUNT also covered |
| N2: grouped functions | All five functions; B/A/C encounter order and literal expected results |
| N3: sorting | Subsequently executed; see sorting validation |
| B1: null targets/keys | All five functions, all-null groups, COUNT of string/grouping columns |
| B2: null/string sorting | Subsequently executed; see sorting validation |
| B3: known-numeric all-null input | All five functions, grouped and ungrouped |
| B4: known-numeric zero rows | All five functions, grouped and ungrouped; sorting subsequently executed |
| B5: header-only/all-null loaded columns | Grouped/ungrouped COUNT and numeric-function semantic rejection; sorting subsequently executed |
| B6: singleton | All five functions, grouped and ungrouped; sorting subsequently executed |
| M1: select/filter/group/sort | Complete workflow subsequently executed; see sorting validation |
| M2: filter/sort aggregate schema | Complete workflow subsequently executed; see sorting validation |
| M3: sort before grouping | Subsequently executed; see sorting validation |
| M4: aggregate an aggregate | Executed; group totals yield AVG 10 |
| M5: contextual sort/asc/desc identifiers | Complete program subsequently executed; see sorting validation |
| I1: invalid cases | Aggregation grammar, lexical COUNT(*), semantic types, missing datasets/columns, removed columns and name collision covered; sorting cases subsequently executed |
| R1: runtime drift | Executed with a temporary CSV changed after semantic analysis/IR generation; numeric runtime guard rejects text and preserves the last successful binding |

Additional executed cases cover an entirely null grouping key, nullable Integer
group keys, output identifier case, independent datasets, repeated aggregation,
downstream projection/filtering, real headless plotting, driver execution and
relative CLI paths. GUI interaction was not validated; later sorting coverage is
recorded separately in sorting validation.

**Commands.**

```text
python3 -B -m pytest tests -q -p no:cacheprovider
python3 -B -m src.main examples/aggregation.dl --ast --ir
```

The implementation was checked stage by stage before proceeding to the next
stage: baseline 45 tests; parser/AST 67; semantic checks 119; IR lowering 123.
The final complete suite passed **199 tests** (the original 45 plus 154 focused
cases) using Python 3.11.9 and pandas 3.0.5. No sorting test is included in that
claim. The non-graphical CLI example also passed through AST display, semantic
analysis, IR generation and execution, producing `[product, sum_revenue]` rows
`(Widget, 1500.5)` and `(Gizmo, 2200.0)` in that order. Interactive GUI behavior
was not exercised.
