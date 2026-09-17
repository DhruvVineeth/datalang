
# DataLang — Language Specification

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
