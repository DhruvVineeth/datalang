# Specification-derived tests

The accepted Phase 3 decisions, README's current semantics, and the hand-calculated
Phase 3 expectation sheet take precedence over the older Phase 1 draft
`langugage-specification.md`: equality is `==`, keywords ignore case, identifiers
retain case, and SORT/ASC/DESC remain contextual. Tests do not derive requirements
from compiler output. Existing tests remain where they were; the new tests are
separated into `tests/unit` and `tests/e2e`.

## Independent oracle

`tests/fixtures/specification/orders.csv` has nine literal rows. Expected rows,
logical schemas, reductions and sort orders are constants in `tests/spec_oracles.py`,
which imports no compiler or data-analysis libraries. No pandas reduction or sort
generates an expected result. Expected source rows are looked up by explicitly
listed row numbers, not ordered with a second sorter.

The present Amount values are 9.5, -1.5, 4, 0, 2, -2 and 8. Their sum is
20; there are seven values; mean is 20/7 = 2.857142857142857; minimum is -2;
maximum is 9.5. Missing targets are skipped, and zero counts as present.

| Team in encounter order | Present Amount values | SUM | AVG | COUNT | MIN | MAX |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| z | 9.5, -1.5 | 8 | 4 | 2 | -1.5 | 9.5 |
| a | none | null | null | 0 | null | null |
| null | 4, 2 | 6 | 3 | 2 | 2 | 4 |
| b | 0, -2 | -2 | -1 | 2 | -2 | 0 |
| c | 8 | 8 | 8 | 1 | 8 | 8 |

All grouped outputs contain exactly Team:String followed by the named aggregate.
COUNT outputs Integer; the other Amount aggregates output Numeric. Grouping
Team itself and counting it yields z:2, a:2, null:0, b:2, c:1. The null-key
group contains two rows but zero present Team values. Taking AVG of the grouped
means ignores a's null and yields (4 + 3 - 1 + 8)/4 = 3.5, not the row mean.

Amount ASC rows are 8,3,6,7,4,9,1,2,5: -2,-1.5,0,2,4,8,9.5 then nulls.
DESC rows are 1,9,4,7,6,3,8,2,5. Team ASC gives a,a,b,b,c,z,z,null,null:
rows 2,5,6,8,9,1,3,4,7; DESC gives 1,3,9,6,8,2,5,4,7. Ties retain their
current input order, including null ties. Units ASC gives rows 2,9 (zero),
4,7 (one), 1,6,8 (two), 3 (three), 5 (four).

The multistage case first sorts Team DESC. Group encounter order is then
z,c,b,a,null. Units sums are respectively 5,0,4,4,2. Sorting these sums DESC
yields z:5,b:4,a:4,null:2,c:0; the b/a tie retains the order established by
the earlier sort. SELECT removes row/Amount before this aggregation.

Filtering `Team == "z" OR Amount >= 4 AND NOT Units == 0` keeps rows 1,3
through the z branch and row 4 through the numeric branch. Row 9 fails because
Units is zero. AND binds tighter than OR; NOT applies to its comparison.

For plotting, keeping rows <=7 then sorting row DESC gives 7,6,5,4,3,2,1.
Present Amount values occur at current-table positions 0,1,3,4,6 and equal
2,0,4,-1.5,9.5. BAR ignores missing Team values and encounters b,a,z with
counts 1,2,2. Tests inspect real rendered Matplotlib artists with Agg.

Zero rows after `row > 9` retain the known numeric Amount schema. Ungrouped
reductions produce one null row, except COUNT produces zero; grouped reductions
produce zero rows with the declared two-column schema and nullable dtypes.

## Test separation and execution

Unit tests invoke one stage/backend in isolation: hand-authored tokens for the
parser, hand-authored AST for semantic analysis and IR, and literal DataFrames
for operations. End-to-end tests call the real driver through every stage and
inspect output values, ordered logical schemas, dtypes, row/index order, dataset
bindings, plots, error stages/coordinates and execution prevention. Observation
subclasses retain the real implementations; parsing never executes data operations.

```powershell
python -B -m pytest tests/unit -q -p no:cacheprovider
python -B -m pytest tests/e2e -q -p no:cacheprovider
python -B -m pytest tests -q -p no:cacheprovider
```

Expected results above are independently calculated. Executed pass counts are
recorded only after the corresponding test commands finish.

Executed: `python3 -B -m pytest tests/unit tests/e2e -q -p no:cacheprovider`
passed all **108 specification tests**. A subsequent focused run of the benchmark
oracle/instrumentation tests passed **14 tests**. These unit/harness executions
are correctness checks, not measured performance results.

After adding the benchmark tests, the full regression command
`python3 -B -m pytest tests -q -p no:cacheprovider` completed with
**616 passed**. This includes the previously existing tests and both new tiers.
