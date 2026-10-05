
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
current table. Plots use the table produced by preceding SELECT/FILTER operations.
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
include source locations; runtime errors include the IR instruction and operation.
Failed compilation or execution returns exit status 1.

Run the tests with `python -m pytest tests`. Visualization tests use the Agg backend
and inspect actual chart data without opening windows.

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
LOAD "sales.csv"
SELECT product, revenue
FILTER revenue > 1000
PLOT BAR product, revenue
