# Sorting implementation and validation

Sorting follows the finalized single-column grammar:

```text
SORT column [ASC|DESC] FROM dataset;
```

ASC is the default. SORT is recognized only at statement start; ASC and DESC
are recognized only after the sorting column. They remain ID tokens everywhere
else, preserving existing valid dataset and column names. Keywords are matched
case-insensitively; identifiers retain their exact case.

**Ordering contract.** Numeric columns use numeric order. Strings use
case-sensitive, locale-independent Unicode lexicographic order. Missing values
are last for ASC and DESC. Ties, including missing-value ties, retain the row
order in the immediate input table, including after a previous sort. Sorting
keeps all rows, columns, column order and dtypes. Empty input stays empty with
the same schema; all-null keys preserve row order. No implicit string/number
coercion is performed.

**Compiler stages.** SortStmt is parsed without any global lexer keyword
additions. Semantic analysis validates the loaded dataset and sorting column
against the current schema and records its types without reshaping it. SortIR
uses the latest runtime table and carries the checked sorting-column type.
The executor checks that runtime values match that type, uses stable sorting
with nulls last, and publishes a fresh table/binding only after success. Missing
or removed columns are semantic errors; runtime schema drift includes SORT
instruction context and leaves the last successful result intact.

**Focused tests.**

| Module | Coverage |
| --- | --- |
| test_sort_parser.py | Defaults/directions, source locations, contextual identifiers, invalid syntax, AST display |
| test_sort_semantic.py | Current schemas, numeric/text keys, missing/removed columns, post-aggregation columns, rejection before lowering/execution |
| test_sort_ir.py | Current input/output temporaries, direction/type metadata, independent datasets, semantic gating, compile-only behavior |
| test_sort_execution.py | Literal expected row orders; nulls/ties; empty/all-null/singleton inputs; aggregate results; source/binding preservation; runtime errors; plotting/driver/CLI integration |

**Executed cases from the hand-calculated expectation sheet.**

| Case | Literal expectations checked |
| --- | --- |
| N3 | Revenue ASC/default IDs 6,5,3,2,4,1; DESC 1,4,2,3,5,6. Quantity ASC 5,2,6,1,4,3; DESC 3,1,4,2,6,5. |
| B2 | Missing numeric keys last, stable IDs 2,3,5,6 among them. Text ASC IDs 2,4,6,3,1,5; DESC 1,3,6,2,4,5. |
| B4/B5/B6 sorting portions | Known-numeric/header-only empty tables preserve schemas; all-null rows retain order; singleton remains unchanged, in both directions. |
| M1 | Select/filter/group/sort retains B=17.5 then A=17.5 because equal totals are stable. |
| M2 | Filtering grouped totals then sorting product gives A=17.5, B=17.5. |
| M3 | Sorting products before grouping yields A=2, B=2, C=2 for COUNT(quantity). |
| M5 | Contextual identifiers execute with output (low,2), (mid,2), (high,1). |
| I1 sorting cases | Invalid direction/multiple keys fail syntax; missing/removed sort columns fail semantics. |
| mixed.csv positive controls | Inferred text values `10` and `oops` sort as strings without numeric coercion. |

Additional cases verify Unicode text, ties relative to a previous sort, nullable
aggregate keys/results, zero-row aggregate outputs, schema drift, independent
datasets and a real headless line chart that receives the sorted table. No
expected order is generated using the implementation's sorting operation.

**Commands.**

```text
python3 -B -m pytest tests -q -p no:cacheprovider
python3 -B -m src.main examples/sorting.dl --ast --ir
```

The focused sorting modules passed all 85 cases: 15 parser, 19 semantic, 6 IR
and 45 runtime/integration cases. The complete suite passed **284 tests**,
including the previous 199-test baseline. The CLI example also passed through
AST display, semantic analysis, IR generation and execution. Its final ordered
`[product, sum_revenue]` rows were `(Gizmo, 2200.0)`, `(Widget, 1500.5)`.
