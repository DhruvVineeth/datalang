## Abstract

**DataLang** is a domain-specific language (DSL) designed to simplify **data analysis and visualization** by compiling declarative analytical specifications into executable **Python code** using `pandas` and `matplotlib`.

Unlike traditional data-analysis workflows that require users to write chained library calls and complex boolean indexing, DataLang allows analysts to express common operations such as **filtering, grouping, aggregation, and plotting** using a concise, task-oriented syntax.

From a **Compiler Design** perspective, DataLang implements a complete language-processing pipeline consisting of:

* **Lexical Analysis** – Tokenization and classification of DataLang source code.
* **Syntax Analysis** – Parsing the input and constructing an **Abstract Syntax Tree (AST)**.
* **Symbol Table Management** – Tracking identifiers and data-related information.
* **Semantic Analysis** – Validating column existence, type compatibility, and operation semantics before execution.
* **Intermediate Representation (IR)** – Lowering the validated AST into an intermediate representation tailored to tabular data operations.
* **Code Generation** – Translating the IR into executable and idiomatic `pandas` and `matplotlib` code.
* **Optimization** – Applying optional optimization passes to eliminate redundant computations and streamline data transformations.
* **Error Handling** – Providing detailed lexical, syntactic, and semantic error messages to improve diagnosability.

The generated Python code remains compatible with the existing **Python data-analysis ecosystem**, allowing users to leverage familiar libraries and tools while interacting with a simpler analytical language.

Overall, DataLang demonstrates how **compiler design techniques can be applied to domain-specific data-analysis languages** to make analytical workflows more accessible, less error-prone, and easier to understand, while maintaining compatibility with established Python-based technologies.
