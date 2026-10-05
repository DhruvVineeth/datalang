"""
DataLang compiler driver.

Lexer → parser → semantic analysis → IR → Pandas execution.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.executor import ExecutionEngine, ExecutionError
from src.interpreter.ir import IRGenerator
from src.lexer.lexer import Lexer, TokenType
from src.parser.parser import ParseError, Parser, print_ast
from src.semantic.semantic import SemanticAnalysisError, SemanticAnalyzer


def compile_source(
    source: str,
    source_dir: Path,
    dump_ast: bool = False,
    dump_ir: bool = False,
    execute: bool = True,
) -> int:
    tokens = Lexer(source).tokenize()
    lexical_errors = [token for token in tokens if token.type == TokenType.ERROR]
    if lexical_errors:
        for token in lexical_errors:
            print(f"Lexical error at line {token.line}, column {token.column}: {token.lexeme}")
        return 1
    try:
        program = Parser(tokens).parse()
    except ParseError as exc:
        print(exc)
        return 1

    if dump_ast:
        print_ast(program)
        print()

    analyzer = SemanticAnalyzer(source_dir=source_dir)
    try:
        table = analyzer.analyze(program)
    except SemanticAnalysisError as exc:
        print(exc)
        return 1

    ir_program = IRGenerator(table).generate(program)

    if dump_ir:
        print("Intermediate representation")
        print(ir_program.format())
        print()

    print("Semantic analysis passed.")
    print()
    print("Symbol table")
    print(table.format_table())

    if not execute:
        return 0

    engine = ExecutionEngine()
    try:
        engine.execute(ir_program)
    except ExecutionError as exc:
        print()
        print(f"Runtime error: {exc}")
        return 1

    result = engine.result()
    print()
    if result is None:
        print("No runtime table was produced.")
    else:
        print(f"Result ({engine.last_output}, {len(result)} row(s))")
        print(result.to_string(index=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="DataLang compiler (semantic analysis, IR, Pandas execution)"
    )
    parser.add_argument("source", nargs="?", help="Path to a .dl program")
    parser.add_argument("--ast", action="store_true", help="Print the AST")
    parser.add_argument("--ir", action="store_true", help="Print the intermediate representation")
    parser.add_argument(
        "--no-execute",
        action="store_true",
        help="Stop after IR generation (do not run the execution engine)",
    )
    args = parser.parse_args(argv)

    if args.source:
        path = Path(args.source)
        if not path.is_file():
            print(f"File not found: {path}")
            return 1
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            print(f"Runtime error: Cannot read source '{path}': {exc}")
            return 1
        return compile_source(
            source,
            source_dir=path.parent,
            dump_ast=args.ast,
            dump_ir=args.ir,
            execute=not args.no_execute,
        )

    print("Usage: python -m src.main <program.dl>")
    return 2


if __name__ == "__main__":
    sys.exit(main())
