# DataLang — Phase 1 Language Specification

This is a scoped-down design suitable for a single-semester compiler lab: enough grammar complexity to exercise a lexer/parser (and later semantic analysis), but small enough that the token set and grammar stay manageable.

## 1. Core Commands

Phase 1 supports five operation categories, each expressed as a statement:

| Command | Purpose | General Form |
|---|---|---|
| `LOAD` | Load a dataset from a file into a named variable | `LOAD "<file>" AS <identifier>` |
| `FILTER` | Keep rows matching a condition | `FILTER <identifier> WHERE <condition>` |
| `SELECT` | Choose a subset of columns | `SELECT <col_list> FROM <identifier>` |
| `AGGREGATE` | Compute summary statistics, optionally grouped | `AGGREGATE <func>(<column>) FROM <identifier> [GROUP BY <column>]` |
| `VISUALIZE` | Produce a chart from a dataset | `VISUALIZE <chart_type> OF <column> FROM <identifier>` |

Each statement ends with a semicolon `;`. A program is a sequence of statements.

## 2. Keywords

Reserved words (case-sensitive, uppercase by convention):

```
LOAD    AS      FILTER  WHERE   SELECT  FROM
AGGREGATE   GROUP   BY      VISUALIZE   OF
AND     OR      NOT
SUM     AVG     COUNT   MIN     MAX
BAR     LINE    SCATTER PIE
```

(You can trim the chart-type and aggregate-function keywords into a single "function identifier" class instead of individual keywords if you want a smaller keyword table — see note at the end.)

## 3. Identifiers

- Used for dataset variable names and column names.
- Rule: `letter (letter | digit | '_')*`
- Case-sensitive.
- Cannot match a reserved keyword.

**Valid:** `sales_data`, `df1`, `Region`, `temp_2024`
**Invalid:** `2data` (starts with digit), `FILTER` (reserved word), `sales-data` (hyphen not allowed)

## 4. Literals

| Type | Description | Examples |
|---|---|---|
| String literal | Enclosed in double quotes; used for file paths and text comparisons | `"sales.csv"`, `"North"` |
| Integer literal | Sequence of digits | `100`, `2024` |
| Float literal | Digits with a single decimal point | `3.14`, `0.5` |

Grammar sketch:
```
STRING   -> '"' char* '"'
INTEGER  -> digit+
FLOAT    -> digit+ '.' digit+
```

## 5. Operators

| Category | Operators | Meaning |
|---|---|---|
| Relational | `=`, `!=`, `<`, `>`, `<=`, `>=` | Used inside `WHERE` conditions |
| Logical | `AND`, `OR`, `NOT` | Combine conditions |

Phase 1 deliberately excludes arithmetic operators (`+`, `-`, `*`, `/`) on values — they can be introduced in Phase 2 for computed columns, keeping Phase 1's grammar focused on filtering/selection logic.

## 6. Delimiters

| Symbol | Use |
|---|---|
| `;` | Statement terminator |
| `,` | Separates items in a column list |
| `(` `)` | Wrap function arguments, e.g. `SUM(price)` |
| `"` `"` | String literal boundaries |

## 7. Example Valid Programs

```
LOAD "sales.csv" AS sales;
FILTER sales WHERE Region = "North" AND Revenue > 1000;
SELECT Region, Revenue FROM sales;
AGGREGATE SUM(Revenue) FROM sales GROUP BY Region;
VISUALIZE BAR OF Revenue FROM sales;
```

```
LOAD "students.csv" AS students;
FILTER students WHERE Grade >= 60 AND NOT Grade > 100;
AGGREGATE AVG(Grade) FROM students;
VISUALIZE LINE OF Grade FROM students;
```

## 8. Example Invalid Programs

```
LOAD sales.csv AS sales;
```
*Invalid: file path is not quoted — a string literal is required.*

```
FILTER sales WHERE Region == "North";
```
*Invalid: `==` is not a defined operator; equality is `=`.*

```
2sales LOAD "sales.csv" AS 2sales;
```
*Invalid: identifier `2sales` begins with a digit.*

```
AGGREGATE SUM Revenue FROM sales
```
*Invalid: missing parentheses around the column argument, and missing statement-terminating semicolon.*

```
VISUALIZE PIE OF Revenue FROM sales AND students;
```
*Invalid: `FROM` clause accepts a single identifier only — `AND` is not valid here (this belongs to `WHERE`, not `FROM`).*

---

