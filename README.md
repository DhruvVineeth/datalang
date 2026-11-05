
# DataLang — Language Specification

## Running the current implementation

Install dependencies with `python -m pip install -r requirements.txt`, then run:

```powershell
python -m src.main examples/visualizations.dl
```

The current compiler uses semicolons and the following single-column visualization syntax:

```text
LOAD "sales.csv" AS sales;
VISUALIZE BAR OF product FROM sales;
VISUALIZE LINE OF revenue FROM sales;
VISUALIZE SCATTER OF quantity FROM sales;
```

BAR displays counts for each distinct non-null value. LINE and SCATTER require
numeric columns and display values against their zero-based positions in the
current table. Plots use the table produced by preceding transformations,
including selection, filtering, aggregation and sorting.
Null values are omitted; empty or entirely null series report a runtime error.
Each chart opens in Matplotlib; close its window to continue execution.
PIE is recognized by the grammar but rejected as unsupported during semantic analysis.

Use `--ast` or `--ir` to inspect compilation, or `--no-execute` to compile without
loading runtime tables or opening charts. For embedding or headless use,
`VisualizationModule(show=False).plot(frame, chart_type, column)` returns a
Matplotlib figure, which can be saved with `figure.savefig("chart.png")` and closed
with `matplotlib.pyplot.close(figure)`.

Errors are reported by stage: **Lexical** (invalid characters/unterminated strings),
**Syntax** (invalid statements/missing delimiters), **Semantic** (unknown datasets,
columns, incompatible types, unavailable CSV schemas), and **Runtime** (failed
CSV reads, invalid runtime operations, or plotting failures). Compiler errors
use one-based source lines and zero-based columns. Runtime errors include the IR
instruction and operation, plus the originating source location when compiled
from DataLang. FILTER errors retain the failing comparison's location even
inside a compound condition. IR generation/display failures are reported as IR
errors before execution. Exit codes are 0 for success, 1 for compilation,
source-reading or execution failure, and 2 for command-line usage errors.
Validation failures prevent executor construction, loading runtime tables and
plotting, including with `--ast`, `--ir` or `--no-execute`. AST/IR dumps are
produced after successful semantic validation. See the
[diagnostics audit](docs/diagnostics-audit.md) for verified examples and tests.

Run the tests with `python -m pytest tests`. Visualization tests use the Agg backend
and inspect actual chart data without opening windows.

Editors can analyze unsaved buffer text independently of the CLI:

```python
from src.editor.analysis import analyze_document

result = analyze_document(text, document_path="examples/program.dl", document_version=7)
for diagnostic in result.diagnostics:
    print(diagnostic.stage, diagnostic.message, diagnostic.line, diagnostic.column)
```

Analysis runs the existing lexer, parser and semantic analyzer, including CSV
schema inference. It prints nothing and stops before IR, optimization, execution
or plotting. Relative LOAD paths use the document's directory; the document need
not exist on disk. The immutable result echoes the document version and absolute
path. Diagnostics have `stage` (`lexical`, `syntax`, `semantic`), `message`,
`severity`, and compiler-style line/column coordinates. `result.ok` indicates
success. `result.datasets` contains dataset names, resolved CSV paths and ordered
`columns` entries with `name` and `data_type`, preserving duplicate projections.
Semantic errors retain the last valid schemas; lexical/syntax errors return no
schemas. Each call reads current CSV schemas and starts with fresh analysis state.

`result.statements` contains immutable before/after schemas for each statement's
named dataset, captured during the same semantic pass. Entries include
`statement_index` (zero-based within the document version), `source_range`,
`dataset_name`, `is_valid`, `before`, and `after`. Ranges start at the statement
keyword and end just after its semicolon, using one-based lines and zero-based
Python character columns. Repeated columns retain their order and multiplicity.
Missing datasets have schema `None`; LOAD has no input schema, and a failed
statement has equal input/output schemas. Later transformations and reanalysis
cannot change earlier snapshots.

```python
schema = result.schema_at(line=3, column=8)  # Input of the containing statement
output = result.schema_at(line=3, column=8, phase="after")
statement = result.statement_at(line=3, column=8)  # Range and validation status
```

Position lookup uses only the containing statement's dataset and returns `None`
outside statement ranges (including whitespace between statements and EOF).
Lexical/syntax failures have no statement snapshots. The result and its nested
snapshots can be serialized with `json.dumps(dataclasses.asdict(result))`;
statement identifiers do not depend on Python object identities.

For incomplete buffers, use the separate cursor API:

```python
from src.editor import analyze_cursor

context = analyze_cursor(text, "examples/program.dl", 8, line=3, column=8)
schema = context.input_schema
active = context.active_statement  # Kind, range, dataset name, completeness
keywords = context.keywords
datasets = context.dataset_names
```

The cursor API checks complete statements before the active statement using
the existing semantic analyzer. `context.prefix` contains that checked prefix's
diagnostics and immutable snapshots. The active statement contributes no schema
changes or semantic diagnostics. Its input schema reflects the current buffer
at its start, even when later statements transform the dataset. Coordinates use
the same line/column convention; positions outside the buffer raise `ValueError`.

SELECT column assistance can resolve a dataset from a later FROM clause in the
same statement, including multiline input and an empty column slot at the
cursor. Without such a clause, `input_schema` is `None`; keyword and known-dataset
assistance is available without choosing a default dataset. Statement boundaries
come from lexer tokens, so semicolons inside strings/comments do not split them.
Unfinished strings and keyword fragments at the cursor remain editor input.

An earlier syntax/lexical error stops schema propagation at the last parsed
statement. `schema_reliable` becomes false and `input_schema` is suppressed;
later statements produce no dependent semantic diagnostics. Known datasets in
the reliable prefix remain available through `dataset_names`. Every call uses
fresh text, CSV schemas and state. Strict document analysis and compilation
continue to reject incomplete input.

The VS Code extension connects through `python -u -m src.editor.bridge`: one
UTF-8 JSON request on stdin, one response on stdout, and logs on stderr. It sends
unsaved text, debounces edits, cancels obsolete requests, and rejects stale
document versions. See the [extension setup and protocol](datalang-vscode/README.md)
for interpreter/backend configuration, dependencies, and request examples.

Aggregation supports one function and an optional single grouping column:

```text
LOAD "sales.csv" AS sales;
AGGREGATE SUM(revenue) FROM sales GROUP BY product;
FILTER sales WHERE sum_revenue > 1000;
VISUALIZE LINE OF sum_revenue FROM sales;
```

SUM, AVG, MIN and MAX require numeric columns; COUNT accepts any column and
counts non-null values. Outputs use names such as `sum_revenue` and
`count_product`, preserving the input column's case after the function prefix.
Aggregation advances the named dataset: the output contains only its optional
grouping column followed by the result column. SELECT likewise updates the
available schema, so later references to removed columns fail semantic analysis.

Null targets are skipped. SUM/AVG/MIN/MAX return null when no values remain;
COUNT returns zero. Null grouping keys form one group, and groups retain their
first-appearance order. Ungrouped empty input produces one result row; grouped
empty input produces zero rows with the checked output schema. Nullable numeric
types are preserved. AVG returns Numeric; COUNT returns Integer; the other
functions retain the target's logical type. All-null or header-only CSV columns
are inferred as String, so numeric aggregation on those loaded columns is rejected.

Run `python -m src.main examples/aggregation.dl --ast --ir` for a complete
non-graphical example. Compilation still passes through semantic analysis and IR
before execution. Standalone GROUP statements remain unimplemented.
See [aggregation validation](docs/phase3-aggregation-validation.md) for executed
coverage against the [hand-calculated expectations](docs/phase3-expected-results.md).

Sorting uses `SORT <column> [ASC|DESC] FROM <dataset>;`, with ascending order
when the direction is omitted. The column must exist in the dataset's current
schema, including after SELECT or AGGREGATE. Numeric columns use numeric order;
text uses case-sensitive Unicode lexicographic order. Missing values always
appear last, in either direction. Sorting is stable: tied rows retain their
order in the input to that SORT statement. All rows, column order and dtypes
are preserved, including for empty input. No implicit text/number conversion is
performed. SORT, ASC and DESC are contextual words, so identifiers named `sort`,
`asc` or `desc` remain valid.

Run `python -m src.main examples/sorting.dl --ast --ir` for sorting after grouped
aggregation. See [sorting validation](docs/phase3-sorting-validation.md) for the
executed numeric, text, missing-value, empty and multi-operation fixture cases.

Schema validation follows each named dataset's current table. SELECT retains
the requested fields in order; FILTER and SORT preserve them; aggregation
replaces them with its optional grouping key and result column. Invalid
statements leave the last valid schema intact. Dataset schemas remain separate,
including when two names load the same CSV. Repeated SELECT fields retain their
runtime order and multiplicity; operations requiring one column reject an
ambiguous repeated name during semantic analysis. See the
[schema propagation audit](docs/schema-propagation-audit.md) for pipeline tests.

The optional IR optimization skips paired `NOT NOT` mask inversions only for
standard Boolean results. It preserves original IR display, source locations,
instruction order and intermediate tables. Use `--no-optimize` to disable it,
or `compile_source(..., optimize=False)` / `ExecutionEngine(optimize=False)` in
Python. See [IR optimization](docs/ir-optimization.md) for exact preconditions,
exclusions and equivalence tests. The benchmark below records measurements;
they do not establish a general performance improvement.

Specification-derived tests are separated into `tests/unit/` and `tests/e2e/`;
their independent calculations are documented in
[specification tests](docs/specification-tests.md). Run either directory separately
or use `python -B -m pytest tests -q -p no:cacheprovider` for all tests.

Run `python -B -m benchmarks.run_benchmark` for deterministic small/medium/larger
datasets, correctness checks, and separate compilation/execution measurements.
The [benchmark methodology](docs/benchmark.md) defines schema-inspection costs
and timing boundaries; [executed results](benchmarks/results/latest.md) link to
the recorded environment and raw samples.

**DataLang: A Domain-Specific Language for Data Analysis and Visualization**

DataLang is a domain-specific language (DSL) designed to simplify common data-analysis and visualization operations through an intuitive, task-oriented syntax.

Instead of requiring users to write general-purpose programming code and library calls for operations such as loading, selecting, filtering, grouping, aggregating, sorting, and visualizing data, DataLang provides dedicated language constructs for these operations.

The DataLang compiler processes a `.dl` source program through lexical analysis, syntax analysis, semantic analysis, symbol table management, intermediate representation, and execution.

---

## Language Overview

DataLang is designed to express common data-analysis and visualization tasks.

The language provides constructs for:

- Loading data from CSV files
- Selecting columns
- Filtering rows
- Grouping data
- Aggregating data
- Sorting data
- Creating visualizations

The language-processing system converts DataLang programs into an intermediate representation and executes the requested data-analysis operations using a Python-based backend.

---

##  Example DataLang Program

A basic DataLang program can be written as:

```text
LOAD "sales.csv" AS sales;
SELECT product, revenue FROM sales;
FILTER revenue > 1000 FROM sales;
VISUALIZE SCATTER OF quantity FROM sales;
