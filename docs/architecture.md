
# DataLang System Architecture

> **DataLang: A Domain-Specific Language for Data Analysis and Visualization**

DataLang is a domain-specific language (DSL) designed to simplify common data-analysis and visualization operations through a concise, task-oriented syntax.

The system follows a compiler-style architecture in which a DataLang source program is transformed through multiple language-processing stages before being executed. The architecture separates **language processing**, **semantic validation**, **intermediate representation**, and **data execution**.

---

## 1. Architecture Overview

The overall processing pipeline of DataLang is:

```text
                   ┌──────────────────────┐
                   │   DataLang Program   │
                   │       (.dl)          │
                   └──────────┬───────────┘
                              │
                              ▼
                   ┌──────────────────────┐
                   │   Lexical Analysis   │
                   │       (Lexer)        │
                   └──────────┬───────────┘
                              │
                              ▼
                   ┌──────────────────────┐
                   │    Token Stream      │
                   └──────────┬───────────┘
                              │
                              ▼
                   ┌──────────────────────┐
                   │   Syntax Analysis   │
                   │      (Parser)        │
                   └──────────┬───────────┘
                              │
                              ▼
                   ┌──────────────────────┐
                   │  Abstract Syntax     │
                   │       Tree (AST)     │
                   └──────────┬───────────┘
                              │
                              ▼
                   ┌──────────────────────┐
                   │  Semantic Analysis   │◄──────────┐
                   └──────────┬───────────┘           │
                              │                       │
                              │                 ┌─────┴──────┐
                              │                 │   Symbol   │
                              │                 │    Table   │
                              │                 └────────────┘
                              ▼
                   ┌──────────────────────┐
                   │ Intermediate         │
                   │ Representation (IR)  │
                   └──────────┬───────────┘
                              │
                              ▼
                   ┌──────────────────────┐
                   │   Execution Engine   │
                   └──────────┬───────────┘
                              │
                    ┌─────────┴─────────┐
                    ▼                   ▼
          ┌──────────────────┐  ┌──────────────────┐
          │  Data Analysis   │  │  Visualization   │
          │     Module       │  │      Module      │
          └────────┬─────────┘  └────────┬─────────┘
                   │                     │
                   └──────────┬──────────┘
                              ▼
                   ┌──────────────────────┐
                   │       Output         │
                   │ Tables / Charts      │
                   └──────────────────────┘
```



---

# 2. Architectural Layers

DataLang can be divided into four major layers:

```text
┌─────────────────────────────────────────────┐
│              SOURCE LANGUAGE                │
│          DataLang Source Program            │
├─────────────────────────────────────────────┤
│             COMPILER FRONT END              │
│  Lexer → Tokens → Parser → AST              │
├─────────────────────────────────────────────┤
│          SEMANTIC / IR PROCESSING           │
│  Symbol Table → Semantic Analysis → IR      │
├─────────────────────────────────────────────┤
│             EXECUTION BACK END              │
│ Execution Engine → Pandas / Matplotlib      │
└─────────────────────────────────────────────┘
```

---

# 3. Component Architecture

## 3.1 DataLang Source Program

The input to the system is a DataLang source file with the `.dl` extension.

The source program contains domain-specific commands such as:

```text
LOAD "sales.csv"
SELECT product, revenue
FILTER revenue > 1000
PLOT BAR product, revenue
```

These commands represent common data-analysis operations without requiring the user to directly write equivalent Python, Pandas, or Matplotlib code.

### Input

```text
.dl DataLang source file
```

### Output

A character stream passed to the lexer.

---

# 4. Lexical Analysis

The **lexer** is the first compiler component.

It reads the characters of the DataLang source program and groups them into meaningful tokens.

The lexer recognizes:

* Keywords
* Identifiers
* String literals
* Numeric literals
* Operators
* Delimiters

For example:

```text
FILTER revenue > 1000
```

is converted into:

```text
FILTER   → KEYWORD
revenue  → IDENTIFIER
>        → OPERATOR
1000     → NUMBER
```

The lexer also detects lexical errors such as:

* Invalid characters
* Malformed literals
* Invalid identifiers
* Unterminated strings

Each token can contain information such as:

```text
Token {
    type
    lexeme
    line
    column
}
```

The line and column information is useful for generating meaningful compiler error messages.

---

# 5. Token Stream

The token stream acts as the interface between the lexer and parser.

It is an ordered sequence of tokens generated by the lexical analyzer.

Example:

```text
Input:
FILTER revenue > 1000

Token Stream:
[
    FILTER,
    IDENTIFIER(revenue),
    GREATER_THAN,
    NUMBER(1000)
]
```

The token stream does not yet contain the hierarchical structure of the program.

That structure is created by the parser.

---

# 6. Syntax Analysis

The **parser** consumes the token stream and checks whether the input follows the grammar defined for DataLang.

The parser is responsible for:

* Validating statement structure
* Detecting syntax errors
* Applying DataLang grammar rules
* Constructing the AST

A simplified grammar can be represented as:

```text
statement
    → load_stmt
    | select_stmt
    | filter_stmt
    | plot_stmt
```

For example:

```text
LOAD "sales.csv"
SELECT product, revenue
FILTER revenue > 1000
PLOT BAR product, revenue
```

is accepted if it follows the defined grammar.

Invalid structures are rejected and reported as syntax errors.

---

# 7. Abstract Syntax Tree

For syntactically valid programs, the parser generates an **Abstract Syntax Tree (AST)**.

The AST represents the logical structure of the DataLang program without unnecessary syntactic details.

For example:

```text
PLOT BAR product, revenue
```

can be represented conceptually as:

```text
        PlotStmt
        /      \
      BAR      Columns
              /      \
         product     revenue
```

A more general AST structure may contain nodes such as:

```text
Program
├── LoadStmt
├── SelectStmt
├── FilterStmt
│   └── Condition
└── PlotStmt
```

The AST becomes the primary input to semantic analysis and later processing stages.

---

# 8. Symbol Table

The **symbol table** is a supporting component used primarily during semantic analysis.

It stores information about datasets, identifiers, columns, and their data types.

Example:

| Name     | Data Type | Symbol Type |
| -------- | --------- | ----------- |
| product  | String    | Column      |
| revenue  | Numeric   | Column      |
| quantity | Integer   | Column      |

The symbol table supports operations such as:

* Symbol insertion
* Symbol lookup
* Data-type tracking
* Column validation
* Dataset tracking

Unlike the main compilation stages, the symbol table does not simply pass data from one stage to another.

Instead, semantic analysis continuously reads from and updates the symbol table.

---

# 9. Semantic Analysis

The semantic analyzer checks whether a syntactically valid DataLang program is logically meaningful.

Syntax alone cannot determine whether an operation is valid.

For example:

```text
LOAD "sales.csv"
FILTER salary > 50000
```

may be syntactically valid but semantically invalid if `salary` does not exist in the loaded dataset.

Semantic analysis performs checks such as:

* Whether the required dataset has been loaded
* Whether referenced columns exist
* Whether data types are compatible
* Whether an operation is applicable to a column
* Whether aggregate functions are valid
* Whether visualization columns exist

### Example

Given:

```text
FILTER revenue > 1000
```

the semantic analyzer checks:

```text
Does revenue exist?
        │
        ├── YES → Is revenue numeric?
        │            │
        │            ├── YES → Valid
        │            └── NO  → Semantic Error
        │
        └── NO → Semantic Error
```

Only semantically valid programs proceed to IR generation.

---

# 10. Intermediate Representation

The **Intermediate Representation (IR)** provides a simplified representation between the DataLang source language and the execution engine.

The IR separates the meaning of a DataLang program from the implementation details of its execution.

For example:

```text
FILTER revenue > 1000
```

can be represented as:

```text
Operation : FILTER
Column    : revenue
Operator  : >
Value     : 1000
```

A more execution-oriented representation can be:

```text
FILTER revenue > 1000
```

or conceptually:

```text
FILTER
  input  = current_table
  column = revenue
  op     = >
  value  = 1000
  output = filtered_table
```

For a larger program:

```text
LOAD sales.csv
SELECT product, revenue
FILTER revenue > 1000
PLOT BAR product, revenue
```

the IR may conceptually become:

```text
LOAD sales.csv → T1

SELECT product, revenue
    T1 → T2

FILTER revenue > 1000
    T2 → T3

PLOT BAR product, revenue
    T3 → OUTPUT
```

The exact internal IR representation will be defined during implementation.

---

# 11. Execution Engine

The execution engine interprets the generated IR and executes the requested operations.

It maintains runtime state, including the actual in-memory tables produced during execution.

The execution engine dispatches each IR operation to the appropriate backend module.

```text
                IR Instruction
                     │
                     ▼
             ┌───────────────┐
             │   Execution   │
             │     Engine    │
             └───────┬───────┘
                     │
           ┌─────────┴─────────┐
           ▼                   ▼
    Data Operation       Plot Operation
           │                   │
           ▼                   ▼
    Data Analysis        Visualization
       Module               Module
```

---

# 12. Data Analysis Module

The Data Analysis Module implements the actual operations on tabular data.

The initial scope includes:

* `LOAD`
* `SELECT`
* `FILTER`
* `GROUP BY`
* `SUM`
* `AVG`
* `COUNT`
* `MIN`
* `MAX`
* `SORT`

The module operates on in-memory tabular data.

The primary data-processing backend is **Pandas**.

Example:

```text
DataLang:

FILTER revenue > 1000
```

Conceptually results in a Pandas operation equivalent to filtering rows based on the `revenue` column.

The DataLang compiler hides the underlying Pandas implementation from the user.

---

# 13. Visualization Module

The Visualization Module converts DataLang plotting operations into graphical output.

The initial visualization scope includes:

```text
PLOT BAR
PLOT LINE
PLOT SCATTER
```

The proposal also identifies support for:

```text
PLOT PIE
```

as part of the visualization module.

Example:

```text
PLOT BAR product, revenue
```

produces a bar chart using the requested columns.

The visualization backend will use **Matplotlib**.


