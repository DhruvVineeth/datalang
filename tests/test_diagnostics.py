"""Stage diagnostics, token/AST/IR provenance, failure gates and actual CLI exits."""

import csv
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.ast import BinaryCondition, Comparison, UnaryCondition
from src.executor import ExecutionEngine, ExecutionError
from src.interpreter.ir import BoolPred, ComparePred, FilterIR, IRError, IRGenerator, IRInstr, IRProgram, LoadIR, NotPred
from src.lexer.lexer import Lexer, TokenType
from src.main import compile_source, main
from src.parser.parser import Parser
from src.semantic.semantic import SemanticAnalysisError, SemanticAnalyzer
from src.symbol_table.symbol_table import SymbolTable


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def source_dir(tmp_path):
    (tmp_path / "data.csv").write_text("x,y,label\n1,2,ok\n2,3,skip\n", encoding="utf-8")
    return tmp_path


def compile_ir(source, source_dir):
    program = Parser(Lexer(source).tokenize()).parse()
    symbols = SemanticAnalyzer(source_dir).analyze(program)
    return program, IRGenerator(symbols).generate(program)


def assert_predicate_locations(ast, ir):
    assert (ir.source_line, ir.source_column) == (ast.line, ast.column)
    if isinstance(ast, Comparison):
        assert isinstance(ir, ComparePred)
    elif isinstance(ast, UnaryCondition):
        assert isinstance(ir, NotPred)
        assert_predicate_locations(ast.operand, ir.operand)
    else:
        assert isinstance(ast, BinaryCondition) and isinstance(ir, BoolPred)
        assert_predicate_locations(ast.left, ir.left)
        assert_predicate_locations(ast.right, ir.right)


def test_source_locations_survive_tokens_ast_and_all_lowered_instructions(source_dir):
    source = '''# comment
  LOAD "data.csv" AS data;
  SELECT label, x FROM data;
  FILTER data WHERE
    NOT x < 0 OR x > 2 AND label != "skip";
  SORT x DESC FROM data;
  AGGREGATE SUM(x) FROM data GROUP BY label;
  VISUALIZE LINE OF sum_x FROM data;'''
    load_token = Lexer(source).tokenize()[0]
    assert (load_token.type, load_token.line, load_token.column) == (TokenType.LOAD, 2, 2)
    program, ir = compile_ir(source, source_dir)
    expected_lines = [2, 3, 4, 6, 7, 8]
    assert [statement.line for statement in program.statements] == expected_lines
    assert [instruction.source_line for instruction in ir.instructions] == expected_lines
    assert all(instruction.source_column == 2 for instruction in ir.instructions)
    ast_condition, ir_condition = program.statements[2].condition, ir.instructions[2].condition
    assert_predicate_locations(ast_condition, ir_condition)
    assert (ir_condition.left.operand.source_line, ir_condition.left.operand.source_column) == (5, 8)
    assert (ast_condition.left.operand.value.line, ast_condition.left.operand.value.column) == (5, 12)


def test_ir_lowering_error_is_located_at_its_statement():
    source = 'LOAD "data.csv" AS data;\n  SORT x FROM data;'
    program = Parser(Lexer(source).tokenize()).parse()
    with pytest.raises(IRError, match="IR error at line 2, column 2:.*must pass semantic analysis") as failure:
        IRGenerator(SymbolTable()).generate(program)
    assert (failure.value.line, failure.value.column) == (2, 2)


@pytest.mark.parametrize("flags", [{}, {"dump_ast": True, "dump_ir": True}, {"execute": False}])
@pytest.mark.parametrize("fragment,stage,message", [
    ("  @", "Lexical", "Unexpected character: @"),
    ("  2sales", "Lexical", "Invalid numeric literal"),
    ('  "unterminated', "Lexical", "Unterminated string"),
    ("  FILTER data WHERE x = 1;", "Lexical", "did you mean =="),
    ("  FILTER data WHERE x >;", "Syntax", "Expected a value"),
    ("  SELECT x FROM data", "Syntax", "end of input"),
    ("  SORT x DOWN FROM data;", "Syntax", "got 'DOWN'"),
    ("  SELECT x FROM unknown;", "Semantic", "has not been loaded"),
    ("  FILTER data WHERE missing > 0;", "Semantic", "does not exist"),
    ("  FILTER data WHERE label > 0;", "Semantic", "not applicable"),
    ("  VISUALIZE PIE OF x FROM data;", "Semantic", "Unsupported chart type"),
    ("  VISUALIZE LINE OF label FROM data;", "Semantic", "numeric column"),
    ('  LOAD "missing.csv" AS missing;', "Semantic", "not found"),
    ('  LOAD "data.csv" AS data;', "Semantic", "already loaded"),
])
def test_validation_errors_stop_before_later_stages(source_dir, monkeypatch, capsys, flags, fragment, stage, message):
    def forbidden(*args, **kwargs):
        raise AssertionError("A validation failure reached a later compiler/runtime stage")
    monkeypatch.setattr("src.main.ExecutionEngine", forbidden)
    monkeypatch.setattr("src.main.IRGenerator.generate", forbidden)
    monkeypatch.setattr("src.main.print_ast", forbidden)
    monkeypatch.setattr("src.executor.DataAnalysisModule.load", forbidden)
    monkeypatch.setattr("src.executor.VisualizationModule.plot", forbidden)
    if stage == "Lexical":
        monkeypatch.setattr("src.main.Parser.parse", forbidden)
    if stage == "Syntax":
        monkeypatch.setattr("src.main.SemanticAnalyzer.analyze", forbidden)
    source = 'LOAD "data.csv" AS data;\n' + fragment
    assert compile_source(source, source_dir, **flags) == 1
    output = capsys.readouterr().out
    assert f"{stage} error at line 2, column" in output and message in output
    assert "Semantic analysis passed." not in output and "Result (" not in output
    assert "Traceback" not in output


def test_multiple_lexical_errors_are_all_reported_without_parsing(source_dir, monkeypatch, capsys):
    def forbidden(*args):
        raise AssertionError("Lexical errors reached parsing")
    monkeypatch.setattr("src.main.Parser.parse", forbidden)
    assert compile_source("@ $\n!", source_dir) == 1
    output = capsys.readouterr().out
    assert output.count("Lexical error") == 3
    assert "line 1, column 0" in output and "line 1, column 2" in output and "line 2, column 0" in output


def test_semantic_comparisons_report_their_own_multiline_locations(source_dir):
    source = 'LOAD "data.csv" AS data;\nFILTER data WHERE\n    missing > 0 OR\n    label > 0;'
    program = Parser(Lexer(source).tokenize()).parse()
    with pytest.raises(SemanticAnalysisError) as failure:
        SemanticAnalyzer(source_dir).analyze(program)
    errors = failure.value.errors
    assert [(error.line, error.column) for error in errors] == [(3, 4), (4, 4)]
    assert "missing" in errors[0].message and "not applicable" in errors[1].message


@pytest.mark.parametrize("flags", [{}, {"dump_ast": True, "dump_ir": True}, {"execute": False}])
def test_deep_logical_tree_is_a_located_semantic_error(source_dir, monkeypatch, capsys, flags):
    def forbidden(*args, **kwargs):
        raise AssertionError("Deep invalid condition reached a later stage")
    monkeypatch.setattr("src.main.IRGenerator.generate", forbidden)
    monkeypatch.setattr("src.main.print_ast", forbidden)
    monkeypatch.setattr("src.main.ExecutionEngine", forbidden)
    source = 'LOAD "data.csv" AS data;\n  FILTER data WHERE ' + " AND ".join(["x > 0"] * 2000) + ";"
    assert compile_source(source, source_dir, **flags) == 1
    output = capsys.readouterr().out
    assert "Semantic error at line 2, column 2: FILTER condition nesting is too deep" in output


def test_csv_reader_errors_are_semantic_diagnostics(source_dir, monkeypatch, capsys):
    (source_dir / "oversized.csv").write_text("x\n" + "a" * (csv.field_size_limit() + 1) + "\n", encoding="utf-8")
    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid CSV schema reached runtime")
    monkeypatch.setattr("src.main.ExecutionEngine", forbidden)
    assert compile_source('\n  LOAD "oversized.csv" AS data;', source_dir) == 1
    output = capsys.readouterr().out
    assert "Semantic error at line 2, column 7:" in output
    assert "oversized.csv" in output and "field" in output


def test_schema_permission_errors_name_dataset_and_csv(source_dir, monkeypatch, capsys):
    def denied(*args, **kwargs):
        raise PermissionError("access denied")
    monkeypatch.setattr("src.semantic.semantic.inspect_csv_schema", denied)
    assert compile_source('\n  LOAD "data.csv" AS data;', source_dir) == 1
    output = capsys.readouterr().out
    assert "Semantic error at line 2, column 7:" in output
    assert "dataset 'data'" in output and "data.csv" in output and "access denied" in output


def test_driver_reports_ir_failure_and_does_not_construct_executor(source_dir, monkeypatch, capsys):
    def fail_lowering(*args):
        raise IRError("cannot lower checked operation", 2, 2)
    def forbidden(*args, **kwargs):
        raise AssertionError("IR failure reached execution")
    monkeypatch.setattr("src.main.IRGenerator.generate", fail_lowering)
    monkeypatch.setattr("src.main.ExecutionEngine", forbidden)
    assert compile_source('LOAD "data.csv" AS data;\n  SORT x FROM data;', source_dir) == 1
    assert "IR error at line 2, column 2: cannot lower checked operation" in capsys.readouterr().out


def test_driver_reports_ir_display_failure_without_execution(source_dir, monkeypatch, capsys):
    def fail_display(*args):
        raise IRError("cannot display checked instruction", 1, 0)
    def forbidden(*args, **kwargs):
        raise AssertionError("IR display failure reached execution")
    monkeypatch.setattr(IRProgram, "format", fail_display)
    monkeypatch.setattr("src.main.ExecutionEngine", forbidden)
    assert compile_source('LOAD "data.csv" AS data;', source_dir, dump_ir=True) == 1
    assert "IR error at line 1, column 0: cannot display checked instruction" in capsys.readouterr().out


@pytest.mark.parametrize("condition,changed,line,column,target", [
    ("    x > 0;", {"x": ["oops"], "y": [2], "label": ["ok"]}, 3, 4, "x"),
    ("    x > 0 AND\n    NOT y > 0;", {"x": [1], "y": ["oops"], "label": ["ok"]}, 4, 8, "y"),
])
def test_runtime_filter_error_uses_closest_predicate_location(source_dir, monkeypatch, condition, changed, line, column, target):
    source = 'LOAD "data.csv" AS data;\nFILTER data WHERE\n' + condition + '\nLOAD "data.csv" AS later;'
    _, ir = compile_ir(source, source_dir)
    engine = ExecutionEngine()
    calls = []
    def changed_load(path):
        calls.append(path)
        return pd.DataFrame(changed)
    monkeypatch.setattr(engine.analysis, "load", changed_load)
    with pytest.raises(ExecutionError, match=rf"Instruction 2 \(FILTER\): Cannot compare column '{target}' using > to 0") as failure:
        engine.execute(ir)
    assert (failure.value.line, failure.value.column) == (line, column)
    assert str(failure.value).count(f"line {line}, column {column}") == 1
    assert len(calls) == 1 and set(engine.tables) == {"T1"}
    assert engine.bindings == {"data": "T1"}


@pytest.mark.parametrize("statement,operation,method", [
    ("SELECT x FROM data;", "SELECT", "select"),
    ("FILTER data WHERE x > 0;", "FILTER", "filter"),
    ("SORT x FROM data;", "SORT", "sort"),
    ("AGGREGATE SUM(x) FROM data;", "AGGREGATE", "aggregate"),
    ("VISUALIZE LINE OF x FROM data;", "PLOT", "plot"),
])
def test_backend_failures_keep_statement_location_and_stop_execution(source_dir, monkeypatch, statement, operation, method):
    _, ir = compile_ir('LOAD "data.csv" AS data;\n  ' + statement + '\nLOAD "data.csv" AS later;', source_dir)
    engine = ExecutionEngine()
    loads = []
    original_load = engine.analysis.load
    def record_load(path):
        loads.append(path)
        return original_load(path)
    def fail(*args, **kwargs):
        raise OSError("simulated backend failure")
    monkeypatch.setattr(engine.analysis, "load", record_load)
    monkeypatch.setattr(engine.visualization if method == "plot" else engine.analysis, method, fail)
    with pytest.raises(ExecutionError) as failure:
        engine.execute(ir)
    assert str(failure.value) == f"Instruction 2 ({operation}): simulated backend failure (line 2, column 2)"
    assert loads and len(loads) == 1
    assert engine.last_output == "T1" and engine.bindings == {"data": "T1"}


def test_missing_runtime_csv_retains_load_location(source_dir):
    _, ir = compile_ir('\n  LOAD "data.csv" AS data;', source_dir)
    (source_dir / "data.csv").unlink()
    with pytest.raises(ExecutionError, match="Instruction 1.*file not found.*line 2, column 2"):
        ExecutionEngine().execute(ir)


def test_runtime_errors_reach_driver_with_location(source_dir, capsys):
    source = 'LOAD "data.csv" AS data;\nFILTER data WHERE x > 10;\n  VISUALIZE LINE OF x FROM data;'
    assert compile_source(source, source_dir) == 1
    output = capsys.readouterr().out
    assert "Runtime error: Instruction 3 (PLOT):" in output
    assert "no non-null values" in output and "line 3, column 2" in output
    assert "Result (" not in output


def test_unknown_ir_instruction_has_runtime_context():
    instruction = IRInstr("UNKNOWN", source_line=7, source_column=3)
    with pytest.raises(ExecutionError, match="Instruction 1.*No executor.*line 7, column 3"):
        ExecutionEngine().execute(IRProgram([instruction]))


def test_manual_ir_without_source_metadata_remains_usable(source_dir):
    engine = ExecutionEngine()
    engine.execute(IRProgram([LoadIR(str(source_dir / "data.csv"), "T1", "data")]))
    assert len(engine.result()) == 2
    with pytest.raises(ExecutionError) as failure:
        engine.execute(IRProgram([IRInstr("UNKNOWN")]))
    assert failure.value.line is None and "column None" not in str(failure.value)


def test_ir_equality_display_matches_accepted_syntax(source_dir):
    _, ir = compile_ir('LOAD "data.csv" AS data; FILTER data WHERE label == "ok";', source_dir)
    assert 'label == "ok"' in ir.format()


@pytest.mark.parametrize("failure", ["missing", "encoding", "permission", "directory"])
def test_source_read_failures_have_nonzero_status_and_prevent_compilation(source_dir, monkeypatch, capsys, failure):
    path = source_dir / "program.dl"
    if failure == "encoding":
        path.write_bytes(b"\xff")
    elif failure == "directory":
        path.mkdir()
    elif failure == "permission":
        path.write_text("", encoding="utf-8")
        def denied(*args, **kwargs):
            raise PermissionError("access denied")
        monkeypatch.setattr(Path, "read_text", denied)
    def forbidden(*args, **kwargs):
        raise AssertionError("Unreadable source reached compilation")
    monkeypatch.setattr("src.main.compile_source", forbidden)
    assert main([str(path)]) == 1
    output = capsys.readouterr().out
    assert "Runtime error:" in output and "program.dl" in output


@pytest.mark.parametrize("source,code,fragment", [
    ('LOAD "data.csv" AS data;', 0, "Result (T1, 2 row(s))"),
    ('LOAD "data.csv" AS data;\n@', 1, "Lexical error at line 2, column 0"),
    ('LOAD "data.csv" AS data', 1, "Syntax error"),
    ('LOAD "data.csv" AS data; SELECT missing FROM data;', 1, "Semantic error"),
    ('LOAD "data.csv" AS data; FILTER data WHERE x > 10; VISUALIZE LINE OF x FROM data;', 1, "Runtime error: Instruction 3 (PLOT)"),
])
def test_real_cli_process_exit_status_and_diagnostics(source_dir, source, code, fragment):
    path = source_dir / "program.dl"
    path.write_text(source, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-B", "-m", "src.main", str(path)],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=20,
    )
    assert result.returncode == code
    assert fragment in result.stdout
    assert "Traceback" not in result.stdout + result.stderr


@pytest.mark.parametrize("arguments,code,fragment", [
    ([], 2, "Usage:"), (["--unknown-option"], 2, "unrecognized arguments"),
    (["does-not-exist.dl"], 1, "Source file not found"),
])
def test_cli_usage_and_source_errors(arguments, code, fragment):
    result = subprocess.run(
        [sys.executable, "-B", "-m", "src.main", *arguments],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=20,
    )
    assert result.returncode == code
    assert fragment in result.stdout + result.stderr
    assert "Traceback" not in result.stdout + result.stderr
