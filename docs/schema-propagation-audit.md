# Schema propagation audit

The audit checks statement-local validation, ordered output fields/types,
failure handling, runtime agreement and named-dataset isolation. Source programs
pass through semantic analysis before IR generation or execution.

**Verified propagation rules.**

| Operation | Required input validation | Successful output schema |
| --- | --- | --- |
| LOAD | File/schema available; dataset name not already loaded | Loaded columns and inferred types, scoped to its dataset name |
| SELECT | Every requested name exists in the current input | Only requested fields, in projection order, retaining their types |
| FILTER | Dataset, columns, operators and literal types checked against current input | Same names, order, multiplicity and types as input |
| SORT | Sorting name is a single available, sortable column | Same names, order, multiplicity and types as input |
| AGGREGATE | Target/key exist and are unambiguous; function accepts target type; generated name does not collide | Optional grouping key first, then generated aggregate column with its specified type |
| VISUALIZE | Current column exists, is unambiguous and meets chart type requirements | Input schema preserved |

The existing ordinary SELECT/aggregate checks already delayed schema mutation
until local validation succeeded. FILTER and SORT preserved their input schemas.
Tests now explicitly exercise these properties, including when validation finds
an error and continues checking later statements against the last valid state.
The driver rejects the entire invalid program before lowering/execution.

**Confirmed mismatch and fix.** Before the fix, this projection had semantic
column names `[product, revenue]` but runtime fields
`[product, product, revenue]`:

```text
LOAD "normal.csv" AS sales;
SELECT product, product, revenue FROM sales;
SORT product FROM sales;
```

SORT passed semantic analysis and failed at runtime with an ambiguous column.
Dataset symbols now retain `column_order`, including repeated fields, alongside
the name-to-type symbol map. Projection expands each requested name to all its
matching input fields, preserving existing valid repeated projections and
subsequent projections. FILTER/SORT/AGGREGATE/VISUALIZE references that require a
single column reject ambiguous names during semantic analysis. An operation on
another unique column remains valid, and ungrouped aggregation may discard
unreferenced repeated fields. The symbol-table display also follows actual field
order. No new grammar or execution path is introduced.

Schema replacement constructs and checks its new field state before publishing
it, preserving dataset identity and LOAD-path metadata. Invalid replacement
orders leave the old schema intact. Earlier IR type snapshots remain separate
from later schema changes; input temporaries continue to track each dataset's
current table independently.

**Focused tests:** `tests/test_schema_propagation.py`.

- Valid SELECT/FILTER/SORT/AGGREGATE pipelines compare semantic fields with
  actual runtime fields. Every prefix of a longer pipeline is checked, including
  repeated aggregation and empty-table paths.
- Invalid selections, comparisons, sorts, aggregation targets/keys/types,
  name collisions and visualizations preserve the last successful schema.
  Generated numeric result types are checked by later comparisons/reductions.
- Validation continues correctly after a failed statement without partial
  schema changes causing false errors in later valid statements.
- Repeated projection order/expansion is preserved; ambiguous scalar references
  fail semantics while unique references and reductions remain usable.
- Two names loading the same file retain separate schemas and runtime tables.
  Different datasets with overlapping names and different column types do not
  contaminate each other. Case-distinct dataset names remain independent.
- Failed/duplicate LOAD operations and invalid schema replacements publish no
  partial state. Invalid pipelines are tested to stop before IR or runtime.

```text
python3 -B -m pytest tests/test_schema_propagation.py -q -p no:cacheprovider
python3 -B -m pytest tests -q -p no:cacheprovider
```

Baseline before this audit: 284 passing tests. Final verification passed all
**341 tests**, including **57 new schema propagation cases**. The original
regressions remain green. Expected values are literal fixture calculations,
not generated using backend transformations. The targeted source/README
whitespace check also passed.
