# Phase 3 fixtures and expected results

**Status: HAND-CALCULATED EXPECTATIONS; EXECUTION TRACKED SEPARATELY.** All results below were calculated
from the finalized semantics and the literal CSV rows. They were not generated
by DataLang, pandas aggregation/sorting, or the existing test suite. These are
test expectations, not evidence by themselves that Phase 3 features work.
The subsequent implementations execute cases recorded in
[aggregation validation](phase3-aggregation-validation.md) and
[sorting validation](phase3-sorting-validation.md). Section labels below retain
their original design-time status; consult those records for later executions.

The fixtures are in [tests/fixtures/phase3](../tests/fixtures/phase3/). This
expectation sheet was created before compiler/executor implementation changes.

**Conventions and execution setup.** Each independent case starts with a fresh
LOAD. Aggregation advances the dataset binding, so consecutive aggregate
statements cannot measure different functions over the same original table
unless the source is loaded again under another name or the case is restarted.

Program fragments below assume the `.dl` file is beside its fixture, or that
`source_dir` points to the fixture directory. For example:

```text
LOAD "normal.csv" AS sales;
AGGREGATE SUM(revenue) FROM sales;
```

For matrix rows, substitute the named function/column into this pattern. For
grouped rows append `GROUP BY product` before the semicolon. Each matrix row is
an independent case. `SORT` without a direction means ascending.

`NULL` in expected tables is a display marker for a missing value, not a new
DataLang literal and not CSV text. Missing CSV fields are blank. Expected result
row order and column order are significant. Row IDs identify source rows; they
do not survive an operation that removes `id` from the output schema. Numeric
formatting such as `30` versus `30.0` is not significant; the logical type is.

**Fixture inventory — expected schemas, not executed inference.**

| CSV | Rows | Expected ordered schema | Purpose |
| --- | ---: | --- | --- |
| [normal.csv](../tests/fixtures/phase3/normal.csv) | 6 | id Integer, product String, revenue Numeric, quantity Integer | Ordinary reductions, negatives, zero, ties and pipelines |
| [nulls.csv](../tests/fixtures/phase3/nulls.csv) | 8 | id Integer, product String, revenue Integer, quantity Integer | Missing targets/keys, all-null groups and stable sorting |
| [words.csv](../tests/fixtures/phase3/words.csv) | 6 | id Integer, product String | Case-sensitive string order, ties and missing strings |
| [empty.csv](../tests/fixtures/phase3/empty.csv) | 0 | id String, product String, revenue String, quantity String | Header-only loading and empty-column inference |
| [all_null.csv](../tests/fixtures/phase3/all_null.csv) | 2 | id Integer, product String, revenue String | All-null loaded column is inferred String |
| [mixed.csv](../tests/fixtures/phase3/mixed.csv) | 2 | id Integer, product String, revenue String | Numeric-looking text mixed with text |
| [collision.csv](../tests/fixtures/phase3/collision.csv) | 2 | id Integer, sum_revenue String, revenue Integer | Group-key/result-name collision |
| [contextual.csv](../tests/fixtures/phase3/contextual.csv) | 3 | id Integer, asc String, desc Integer | Preserve identifiers named sort/asc/desc |

Normal revenue contains decimal points, so it is Numeric. Nulls revenue has
only integer non-null values, so it is Integer. Empty/all-null columns have no
values establishing a numeric type, so their expected inferred type is String.
The text `oops` makes mixed revenue String; it must not be silently coerced.

**N1 — normal ungrouped aggregations, expected and unexecuted.**

Load normal.csv afresh for every row below. Each output has exactly one row and
one column named `function_column`, with the function lowercased.

| Function | revenue result (output name) | quantity result (output name) | Calculation |
| --- | --- | --- | --- |
| SUM | 30 (`sum_revenue`, Numeric) | 9 (`sum_quantity`, Integer) | Revenue: 12.5 + 7.5 + 5 + 10 + 0 - 5 = 30. Quantity: 2 + 1 + 3 + 2 + 0 + 1 = 9. |
| AVG | 5 (`avg_revenue`, Numeric) | 1.5 (`avg_quantity`, Numeric) | Six non-null values: 30 / 6 = 5 and 9 / 6 = 1.5. |
| COUNT | 6 (`count_revenue`, Integer) | 6 (`count_quantity`, Integer) | All six cells are present. Zero and negative values count. |
| MIN | -5 (`min_revenue`, Numeric) | 0 (`min_quantity`, Integer) | Smallest values in the respective columns. |
| MAX | 12.5 (`max_revenue`, Numeric) | 3 (`max_quantity`, Integer) | Largest values in the respective columns. |

`COUNT(product)` also returns `[count_product: Integer]` with one row containing
6: repeated values are counted, not deduplicated.

**N2 — grouped normal aggregations, expected and unexecuted.**

Run each function independently on normal.csv with `GROUP BY product`. The
table below combines five separate expected outputs for readability. Each real
output has only `[product, function_revenue]`.

| product, in expected order | SUM | AVG | COUNT | MIN | MAX |
| --- | ---: | ---: | ---: | ---: | ---: |
| B | 17.5 | 8.75 | 2 | 5 | 12.5 |
| A | 17.5 | 8.75 | 2 | 7.5 | 10 |
| C | -5 | -2.5 | 2 | -5 | 0 |

B contains 12.5 and 5: total 17.5, mean 17.5 / 2 = 8.75, two values, extrema
5 and 12.5. A contains 7.5 and 10: total 17.5, mean 8.75, two values, extrema
7.5 and 10. C contains 0 and -5: total -5, mean -5 / 2 = -2.5, two values,
extrema -5 and 0. B precedes A because B occurs first in the source, even though
A would sort first alphabetically. Result types follow N1.

**N3 — normal numeric sorting, expected and unexecuted.**

| Statement after loading normal.csv | Expected source ID order | Explanation |
| --- | --- | --- |
| `SORT revenue FROM sales;` | 6, 5, 3, 2, 4, 1 | Values ascend: -5, 0, 5, 7.5, 10, 12.5. |
| `SORT revenue DESC FROM sales;` | 1, 4, 2, 3, 5, 6 | Values descend: 12.5, 10, 7.5, 5, 0, -5. |
| `SORT quantity ASC FROM sales;` | 5, 2, 6, 1, 4, 3 | Values: 0, 1, 1, 2, 2, 3. Tied IDs 2/6 and 1/4 retain source order. |
| `SORT quantity DESC FROM sales;` | 3, 1, 4, 2, 6, 5 | Values: 3, 2, 2, 1, 1, 0. Descending order still preserves each tie's source order. |

Every sort retains all four columns, their types, and all six rows.

**B1 — missing targets and grouping keys, expected and unexecuted.**

For ungrouped reductions of nulls.csv revenue, the present values are 10, 5,
0 and -5. Therefore SUM = 10 + 5 + 0 - 5 = 10; AVG = 10 / 4 = 2.5;
COUNT = 4; MIN = -5; MAX = 10. SUM/MIN/MAX have Integer logical type; AVG is
Numeric and COUNT is Integer. The four missing targets are excluded, not zeroed.

For independent grouped revenue reductions:

| product, in expected order | SUM | AVG | COUNT | MIN | MAX |
| --- | ---: | ---: | ---: | ---: | ---: |
| B | 10 | 10 | 1 | 10 | 10 |
| A | NULL | NULL | 0 | NULL | NULL |
| NULL | 5 | 5 | 1 | 5 | 5 |
| C | -5 | -2.5 | 2 | -5 | 0 |

B has one present value, 10. A has two rows but no present revenue, so its
numeric reductions are null and its count is zero. The null-key rows form one
group, with targets 5 and null; only 5 contributes. C contributes 0 and -5.
The groups first appear as B, A, NULL, C. Missing-key rows are retained.

Independently, `COUNT(product)` is 6 globally: IDs 1, 2, 3, 5, 7 and 8 have
present products. With `GROUP BY product`, expected `[product, count_product]`
rows are `(B, 2), (A, 2), (NULL, 0), (C, 2)`. The null-key group has two rows
but zero present product values. This also tests aggregating the grouping column
itself without creating duplicate output names.

**B2 — null placement and string order, expected and unexecuted.**

| Fixture and statement | Expected source ID order | Explanation |
| --- | --- | --- |
| nulls.csv: `SORT revenue ASC FROM sales;` | 8, 7, 4, 1, 2, 3, 5, 6 | Present values -5, 0, 5, 10 first; missing values last, retaining IDs 2, 3, 5, 6 in order. |
| nulls.csv: `SORT revenue DESC FROM sales;` | 1, 4, 7, 8, 2, 3, 5, 6 | Present values 10, 5, 0, -5; missing values remain last. |
| words.csv: `SORT product ASC FROM sales;` | 2, 4, 6, 3, 1, 5 | Case-sensitive order A, A, B, a, b, NULL; equal A values retain IDs 2 then 4. |
| words.csv: `SORT product DESC FROM sales;` | 1, 3, 6, 2, 4, 5 | Order b, a, B, A, A, NULL; the A tie still retains IDs 2 then 4. |

Each case retains the fixture's complete original schema and rows.

**B3 — known-numeric all-null input, expected and unexecuted.**

```text
LOAD "nulls.csv" AS sales;
FILTER sales WHERE product == "A";
AGGREGATE SUM(revenue) FROM sales;
```

The filter retains IDs 2 and 5. Revenue retains its Integer schema, but both
values are missing. The expected output is one row `[sum_revenue: Integer]`
containing NULL, not zero. Starting over and substituting AVG, COUNT, MIN or MAX
gives NULL, 0, NULL or NULL respectively. AVG is Numeric; COUNT is Integer.
Adding `GROUP BY product` produces one A row with the same result, because A
exists as a group even though its targets are all missing.

**B4 — known-numeric zero-row input, expected and unexecuted.**

```text
LOAD "normal.csv" AS sales;
FILTER sales WHERE id > 100;
AGGREGATE SUM(revenue) FROM sales;
```

The largest ID is 6, so zero rows survive. The numeric revenue schema survives
the filter. Ungrouped SUM/AVG/MIN/MAX each produce one null result row; COUNT
produces one integer-zero row. SUM/MIN/MAX remain Numeric here, as in normal.csv.

Repeating each case with `GROUP BY product` instead produces zero rows, with
schema `[product: String, function_revenue: corresponding result type]`.
There are no groups to emit. Replacing the aggregate with either direction of
`SORT revenue` yields zero rows and the original four-column schema.

**B5 — header-only and all-null loaded columns, expected and unexecuted.**

For empty.csv, COUNT(revenue) produces one Integer-zero row: there are no present
values. Grouped COUNT(revenue) produces zero rows with schema
`[product: String, count_revenue: Integer]`. Sorting revenue in either direction
returns zero rows and the four String columns.

SUM/AVG/MIN/MAX(revenue) on empty.csv each cause a semantic type error: a
header alone does not establish numeric type. The same four errors are expected
on all_null.csv. For that fixture COUNT(revenue) is zero globally, or grouped
rows `(A, 0), (B, 0)`. Both rows have missing revenue, but distinct present keys.
Sorting its revenue retains IDs 1, 2 in either direction because both keys are
null and the sort is stable.

**B6 — singleton input, expected and unexecuted.**

Filter normal.csv using `id == 1` before independently applying each function.
The sole present revenue is 12.5. SUM, AVG, MIN and MAX therefore each return
12.5, and COUNT returns 1. Grouped versions contain exactly one row with key B.
Sorting this singleton preserves its sole row. This checks that AVG does not
require two observations and MIN/MAX do not fail on a singleton.

**M1 — selection, filtering, grouping and stable result sorting, expected and unexecuted.**

```text
LOAD "normal.csv" AS sales;
SELECT product, revenue FROM sales;
FILTER sales WHERE revenue >= 5;
AGGREGATE SUM(revenue) FROM sales GROUP BY product;
SORT sum_revenue DESC FROM sales;
```

SELECT removes id/quantity. FILTER keeps original IDs 1, 2, 3 and 4; C's
values 0 and -5 fail the threshold. B totals 12.5 + 5 = 17.5; A totals
7.5 + 10 = 17.5. Group creation order is B, A, and equal totals retain that
order under descending stable sorting.

Expected final schema is `[product: String, sum_revenue: Numeric]`; expected
rows are `(B, 17.5), (A, 17.5)`.

**M2 — filtering and sorting the aggregate schema, expected and unexecuted.**

```text
LOAD "normal.csv" AS sales;
AGGREGATE SUM(revenue) FROM sales GROUP BY product;
FILTER sales WHERE sum_revenue > 0;
SORT product ASC FROM sales;
```

The grouped rows are B=17.5, A=17.5, C=-5. The filter removes C because -5
is not greater than zero. String sorting puts A before B. Expected final rows
are `(A, 17.5), (B, 17.5)` with the same two-column schema as M1.

**M3 — sorting before grouping changes group encounter order, expected and unexecuted.**

```text
LOAD "normal.csv" AS sales;
SORT product ASC FROM sales;
AGGREGATE COUNT(quantity) FROM sales GROUP BY product;
```

Sorting produces source IDs 2, 4, 1, 3, 5, 6, so groups first appear A, B, C.
Each has two present quantity values. In particular C's 0 and 1 both count.
Expected schema is `[product: String, count_quantity: Integer]`; expected rows
are `(A, 2), (B, 2), (C, 2)`.

**M4 — aggregate an aggregate result, expected and unexecuted.**

```text
LOAD "normal.csv" AS sales;
AGGREGATE SUM(revenue) FROM sales GROUP BY product;
AGGREGATE AVG(sum_revenue) FROM sales;
```

The second operation consumes 17.5, 17.5 and -5, not the original six revenues.
Their total is 30 and there are three groups, giving 30 / 3 = 10. Expected
schema is `[avg_sum_revenue: Numeric]` with one row containing 10. This differs
from the original row-level mean of 5 and detects an incorrect source binding.

**M5 — preserve contextual identifiers, expected and unexecuted.**

```text
LOAD "contextual.csv" AS sort;
SELECT asc, desc FROM sort;
SORT desc DESC FROM sort;
```

The first `desc` after SORT is the column name; the second is the direction.
Descending values are 2, 2, 1. Tied original IDs 1 and 3 keep their order.
Expected schema is `[asc: String, desc: Integer]`; expected rows are
`(low, 2), (mid, 2), (high, 1)`. Reserving sort/asc/desc globally would wrongly
reject this program.

**I1 — expected invalid cases, all unexecuted.**

Unless stated otherwise, precede the fragment with a fresh
`LOAD "normal.csv" AS sales;`. Error wording is illustrative; the required
assertions are the stage, relevant identifier/reason, source location and
absence of successful execution of the invalid program.

| Case / fragment | Expected error stage | Explanation |
| --- | --- | --- |
| `AGGREGATE SUM revenue FROM sales;` | Syntax | Function arguments require parentheses. |
| `AGGREGATE SUM(revenue) FROM sales` | Syntax | Missing terminating semicolon. |
| `AGGREGATE MEDIAN(revenue) FROM sales;` | Syntax | MEDIAN is outside the five-function grammar. |
| `AGGREGATE COUNT(*) FROM sales;` | Lexical | `*` is not a supported token; COUNT requires a column. |
| `AGGREGATE SUM(revenue), AVG(revenue) FROM sales;` | Syntax | A statement accepts exactly one function. |
| `AGGREGATE SUM(revenue) FROM sales GROUP BY product, quantity;` | Syntax | Exactly one grouping column is allowed. |
| `AGGREGATE SUM(revenue) FROM sales GROUP BY;` | Syntax | Grouping column is missing. |
| `SORT revenue DOWN FROM sales;` | Syntax | Direction must be ASC/DESC, or omitted. |
| `SORT revenue, quantity FROM sales;` | Syntax | Exactly one sorting column is allowed. |
| `AGGREGATE SUM(revenue) FROM unknown;` | Semantic | Dataset unknown has not been loaded. |
| `AGGREGATE SUM(missing) FROM sales;` | Semantic | Target column does not exist. |
| `AGGREGATE SUM(revenue) FROM sales GROUP BY missing;` | Semantic | Grouping column does not exist. |
| `SORT missing FROM sales;` | Semantic | Sorting column does not exist. |
| `AGGREGATE SUM(product) FROM sales;` | Semantic | SUM requires Integer/Numeric, but product is String. |
| Substitute AVG, MIN or MAX for SUM(product) | Semantic | All four numeric functions reject String under the finalized scope. |
| `SELECT product FROM sales; AGGREGATE SUM(revenue) FROM sales;` | Semantic | SELECT removed revenue from the current schema. |
| `SELECT product FROM sales; SORT revenue FROM sales;` | Semantic | Sorting cannot restore a removed column. |
| `AGGREGATE SUM(revenue) FROM sales GROUP BY product; SORT revenue FROM sales;` | Semantic | Current columns are product/sum_revenue; raw revenue is gone. |
| Load collision.csv, then `AGGREGATE SUM(revenue) FROM sales GROUP BY sum_revenue;` | Semantic | Both output columns would be named sum_revenue; silent renaming is forbidden. |
| Load mixed.csv, then SUM/AVG/MIN/MAX(revenue), each independently | Semantic | The target's String type includes `oops`; skip/coerce behavior would be incorrect. |

Independent positive controls for mixed.csv: COUNT(revenue) returns 2 because
both `10` and `oops` are present strings; sorting revenue ASC yields IDs 1, 2,
because string `10` precedes string `oops`. Each sort retains all three columns.

**R1 — runtime schema drift, expected and unexecuted.**

This requires a future controlled execution harness rather than only a static
CSV. Make a temporary copy of normal.csv; compile LOAD plus
`AGGREGATE SUM(revenue) FROM sales;` without executing it. Then replace one
revenue with `oops` in that temporary copy and execute the already-compiled IR.
The expected result is a runtime schema/type error with instruction context,
not concatenation, coercion to null, or a successful numeric result. No new
aggregate-result binding should be published. A LOAD schema guard could detect
the mismatch at Instruction 1 (LOAD); otherwise it must be detected at
Instruction 2 (AGGREGATE). The finalized semantics do not require choosing one
of those detection points. Do not change the checked-in fixture for this case.

**Verification status.** At design time only fixture structure was checked
(headers, field counts, row counts). Expected values have not been regenerated
from the implementation. Later actual execution coverage is recorded separately
in [aggregation validation](phase3-aggregation-validation.md) and
[sorting validation](phase3-sorting-validation.md); uncovered cases remain
EXPECTED / NOT EXECUTED.
