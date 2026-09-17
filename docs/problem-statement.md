
# Problem Statement

Conventional data-analysis workflows often require users to move repeatedly between different tools for importing data, cleaning and transforming it, performing calculations, and producing visualizations. These steps are frequently expressed through general-purpose programming languages, command-line utilities, or separate graphical applications.

As a result, even common analysis tasks can involve **lengthy, repetitive code** and **inconsistent descriptions of the intended workflow**. The gap between what a user wants to express—such as filtering a dataset, grouping records, computing summaries, and displaying trends—and how those operations must be programmed makes data analysis **more difficult to learn, read, and reproduce**.

A **Domain-Specific Language (DSL)** designed specifically for data analysis and visualization can address this problem by providing concise, domain-oriented constructs that represent common analytical operations directly. Such a language can make analysis specifications clearer while reducing unnecessary general-purpose programming overhead.

From a **Compiler Design** perspective, the problem is to define the syntax and semantics of such a language and develop a language-processing system capable of:

* Recognizing valid data-analysis descriptions.
* Detecting lexical, syntactic, and semantic errors.
* Representing valid programs using an Abstract Syntax Tree (AST).
* Managing dataset and column information through a symbol table.
* Translating DataLang programs into an appropriate intermediate representation.
* Executing the validated analytical operations and visualizations.

The project therefore investigates how **Compiler Design principles can be applied to create a focused domain-specific language for expressing basic data-analysis and visualization tasks** in a concise and intuitive manner.
