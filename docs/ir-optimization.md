# Conservative IR optimization: guarded double NOT

**New design decision:** enable one optional execution optimization after
successful semantic analysis and IR generation: `NOT NOT P` can evaluate as `P`
when the evaluated mask is a standard Boolean Series. No grammar or semantic
rules change. This is implemented as an IR execution hint, retaining the original
two NOT nodes rather than deleting their diagnostic provenance.

## Inspection and choice

`src/interpreter/ir.py` represents programs as ordered table instructions. FILTER
conditions use ComparePred, NotPred and BoolPred. Every transformation produces
a named temporary; `ExecutionEngine.tables` retains all of them, dataset bindings
advance to the current temporary, and runtime errors identify the instruction
number and the most precise available source location.

Removing, combining or moving table instructions could alter that state or error
ordering. This rule only avoids two mask inversions inside one FILTER. All
instructions, temporary names, comparisons, operand evaluation order and eager
AND/OR evaluations remain in place. LOAD and PLOT side effects retain their order.

## Exact preconditions and exclusions

| Condition | Required behavior |
| --- | --- |
| Compiler stage | Run the pass only after the existing semantic validation and IR lowering succeed. Invalid source never reaches the pass or executor. |
| Predicate structure | The complete FILTER tree contains only exact ComparePred, NotPred and BoolPred classes, recognized comparison operators and AND/OR. A candidate is an exact NotPred whose immediate operand is another exact NotPred. |
| Graph shape | Shared, cyclic, unknown, custom or unsupported predicate graphs are left untouched. An isolated NOT, comparisons without a double NOT, and other instructions receive no hint. |
| Backend and table | The engine uses exactly DataAnalysisModule and a plain pandas DataFrame. Custom analysis backends and DataFrame subclasses execute the original predicate path. |
| Runtime mask | The evaluated inner operand is exactly pandas Series, with native NumPy bool dtype and pandas' built-in NumPy-backed array, or exactly pandas BooleanDtype with exactly BooleanArray. Only then may both inversions be skipped. |
| Other masks | Integer, object, string, custom Series/extension arrays and other results retain both inversions and their original exception contexts. No coercion is introduced. |
| Off mode | `--no-optimize` bypasses the IR pass. `compile_source(..., optimize=False)` does the same for API callers. `ExecutionEngine(optimize=False)` ignores hints even in previously optimized IR. |

Do not generalize this to short-circuiting AND/OR, De Morgan rewrites, changing
comparison operators, predicate reordering, removing duplicate FILTER statements,
or pushing filters through SELECT, SORT, aggregation or plotting. None of those
rewrites is implemented or implied by this rule.

## Equivalence argument and diagnostics

For native Boolean values, `~~True == True` and `~~False == False`. Nullable
Boolean inversion also leaves a missing value missing, so double inversion
preserves `[True, False, NA]`. The operand still executes exactly once; its
comparisons and nested predicates are unchanged. The resulting mask retains its
values, dtype, index, name and attributes, and the existing FILTER still treats
missing mask entries as false. CSV NaN comparison behavior is also unchanged:
the rule never rewrites the comparison or introduces a different null policy.

The pass copies changed FILTER instructions and predicates, leaving the input IR
untouched. It keeps original predicate structure, source coordinates, instruction
count, input/output temporary names and ordinary IR formatting. Thus `--ast` and
`--ir` output remain identical in both modes. The hint is excluded from dataclass
equality and representation. `optimize_ir(..., enabled=False)` bypasses annotation;
use the engine's off switch to ignore hints already present in an IR object.

The inner NOT's exception context is retained while evaluating its operand.
Operand failures keep their own location when available; otherwise the original
inner NOT fallback location applies. For ineligible masks, failures in the first
inversion still point to that inner NOT, and failures in the second inversion
still point to the outer NOT. Statement-level diagnostics, first failure order,
partial table state and execution prevention are unchanged.

## Use and verification

```powershell
python -m src.main examples/sorting.dl --ir
python -m src.main examples/sorting.dl --ir --no-optimize
python -m pytest tests/test_optimizer.py
```

An eligible example is `FILTER sales WHERE NOT NOT revenue > 7;`. Existing
programs without double NOT have no eligible predicate and receive no execution
rewrite.

`tests/test_optimizer.py` compares optimization on and off using the validated
compiler pipeline. It covers hand-specified numeric/text fixture results, null
and empty inputs, nested NOT, eager AND/OR failures, nullable post-aggregation
filters, SELECT/SORT pipelines, named dataset isolation and plot inputs/order.
It compares every intermediate DataFrame, including row/column order, index and
dtypes; bindings; final temporary; error text/coordinates; and actual CLI stdout,
stderr and exit status with debug and no-execution flags. Additional focused tests
cover mask metadata, fallback behavior, custom backends, unchanged IR provenance,
graph exclusions and validation preventing optimization/execution.

Executed verification: the baseline was **435 passing tests**; the full regression
suite now has **494 passing tests**, including **59 optimization cases**. The
initial focused run passed all 48 cases present before the final additions.
An inversion-call spy checks
that an eligible pair skips two inversions when enabled and executes both when
disabled. This verifies application of the rule; it is not a timing measurement.
At implementation time no performance benchmark was run. Subsequent measurements
are recorded separately in the [benchmark report](../benchmarks/results/latest.md)
and [methodology](benchmark.md); they do not establish a general speed or memory
improvement.
