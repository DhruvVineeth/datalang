"""Run with python -B -m benchmarks.run_benchmark; see docs/benchmark.md."""

from __future__ import annotations

import argparse
import csv
import gc
import hashlib
import importlib.metadata
import json
import os
import platform
import statistics
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import get_clock_info, perf_counter_ns
from unittest.mock import patch

import numpy as np
import pandas as pd

import src.semantic.semantic as semantic_module
from src.executor import ExecutionEngine
from src.interpreter.ir import IRGenerator
from src.interpreter.optimizer import optimize_ir
from src.lexer.lexer import Lexer, TokenType
from src.parser.parser import Parser
from src.semantic.semantic import SemanticAnalyzer


ROOT = Path(__file__).resolve().parents[1]
SIZES = (("small", 1_000), ("medium", 10_000), ("larger", 100_000))
PATTERN = (
    ("z", 9.5, 2), ("a", None, 0), ("z", -1.5, 3),
    (None, 4.0, 1), ("a", None, 4), ("b", 0.0, 2),
    (None, 2.0, 1), ("b", -2.0, 2), ("c", 8.0, 0),
)
SOURCE = '''LOAD "data.csv" AS data;
SELECT group_key, amount, units FROM data;
FILTER data WHERE NOT NOT units >= 1;
AGGREGATE SUM(amount) FROM data GROUP BY group_key;
SORT sum_amount DESC FROM data;
'''
STAGES = ("lex_ns", "parse_ns", "semantic_total_ns", "schema_inspection_ns",
          "ir_ns", "optimize_ns", "compile_total_ns", "execute_ns")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def generate(path: Path, rows: int):
    if rows < 9:
        raise ValueError("At least nine rows are required to exercise the complete pattern")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(("row", "group_key", "amount", "units"))
        for index in range(rows):
            key, amount, units = PATTERN[index % 9]
            writer.writerow((index + 1, key, amount, units))


def expected_result(rows):
    """Closed-form oracle, independent of CSV reading and pandas reductions/sorts."""
    if rows < 9:
        raise ValueError("At least nine rows are required")
    cycles, tail = divmod(rows, 9)
    z = 8 * cycles + (9.5 if tail >= 1 else 0) - (1.5 if tail >= 3 else 0)
    null_key = 6 * cycles + (4 if tail >= 4 else 0) + (2 if tail >= 7 else 0)
    b = -2 * cycles - (2 if tail >= 8 else 0)
    # Of each complete cycle, only the two zero-unit rows are removed.
    selected = 7 * cycles + (0, 1, 1, 2, 3, 4, 5, 6, 7)[tail]
    return (("z", z), (None, null_key), ("b", b), ("a", None)), selected


def compile_program(directory, optimized):
    schema_ns, schema_calls = [], []
    inspect = semantic_module.inspect_csv_schema

    def timed_inspect(path):
        begin = perf_counter_ns()
        try:
            return inspect(path)
        finally:
            schema_ns.append(perf_counter_ns() - begin)
            schema_calls.append(str(path))

    # Install instrumentation outside compilation; its two clock reads per LOAD
    # are included. The original callable is restored even on compilation failure.
    with patch.object(semantic_module, "inspect_csv_schema", timed_inspect):
        t0 = perf_counter_ns()
        tokens = Lexer(SOURCE).tokenize()
        if any(token.type is TokenType.ERROR for token in tokens):
            raise ValueError("Benchmark program failed lexical analysis")
        t1 = perf_counter_ns()
        ast = Parser(tokens).parse()
        t2 = perf_counter_ns()
        symbols = SemanticAnalyzer(directory).analyze(ast)
        t3 = perf_counter_ns()
        ir = IRGenerator(symbols).generate(ast)
        t4 = perf_counter_ns()
        ir = optimize_ir(ir, enabled=optimized)
        t5 = perf_counter_ns()
    if len(schema_calls) != 1:
        raise AssertionError("Expected exactly one full CSV schema inspection per compilation")
    schema = {name: column.data_type for name, column in symbols.lookup("data").columns.items()}
    if schema != {"group_key": "String", "sum_amount": "Numeric"}:
        raise AssertionError(f"Incorrect checked output schema: {schema}")
    return ir, {
        "lex_ns": t1 - t0, "parse_ns": t2 - t1, "semantic_total_ns": t3 - t2,
        "schema_inspection_ns": sum(schema_ns), "schema_inspection_calls": len(schema_calls),
        "ir_ns": t4 - t3, "optimize_ns": t5 - t4, "compile_total_ns": t5 - t0,
    }


def verify(engine, rows):
    expected, selected = expected_result(rows)
    result = engine.result()
    if result is None or list(result.columns) != ["group_key", "sum_amount"]:
        raise AssertionError("Incorrect result columns")
    actual = tuple(tuple(None if pd.isna(value) else value for value in row)
                   for row in result.itertuples(index=False, name=None))
    if actual != expected:
        raise AssertionError(f"Incorrect result: {actual!r}; expected {expected!r}")
    if [str(dtype) for dtype in result.dtypes] != ["string", "Float64"]:
        raise AssertionError("Incorrect nullable output dtypes")
    if list(result.index) != [0, 1, 3, 2]:
        raise AssertionError("Incorrect stable result ordering/index")
    if list(engine.tables) != ["T1", "T2", "T3", "T4", "T5"]:
        raise AssertionError("Missing intermediate tables")
    if [len(frame) for frame in engine.tables.values()] != [rows, rows, selected, 4, 4]:
        raise AssertionError("Incorrect intermediate cardinality")
    if engine.bindings != {"data": "T5"} or engine.last_output != "T5":
        raise AssertionError("Incorrect final dataset binding")


def environment():
    clock = get_clock_info("perf_counter")
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    status = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True)
    paths = sorted((ROOT / "src").rglob("*.py")) + [Path(__file__).resolve()]
    return {
        "python": sys.version, "python_implementation": platform.python_implementation(),
        "executable": sys.executable, "os": platform.platform(), "machine": platform.machine(),
        "processor": platform.processor(), "logical_cpus": os.cpu_count(),
        "pandas": pd.__version__, "numpy": np.__version__,
        "matplotlib": importlib.metadata.version("matplotlib"),
        "clock": {"implementation": clock.implementation, "resolution_seconds": clock.resolution,
                  "monotonic": clock.monotonic},
        "gc_enabled": gc.isenabled(),
        "thread_environment": {key: os.environ.get(key) for key in (
            "OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "PYTHONHASHSEED")},
        "git_commit": revision.stdout.strip() if revision.returncode == 0 else None,
        "git_status": status.stdout.splitlines() if status.returncode == 0 else None,
        "source_sha256": {str(path.relative_to(ROOT)).replace("\\", "/"): digest(path) for path in paths},
    }


def summarize(samples):
    return {stage: {
        "median_ns": statistics.median(sample[stage] for sample in samples),
        "min_ns": min(sample[stage] for sample in samples),
        "max_ns": max(sample[stage] for sample in samples),
        "stdev_ns": statistics.stdev(sample[stage] for sample in samples) if len(samples) > 1 else 0,
    } for stage in STAGES}


def benchmark(data_dir, sizes=SIZES, repetitions=5, warmups=1):
    if repetitions < 2 or warmups < 0:
        raise ValueError("Use at least two measured repetitions and zero or more warmups")
    # Verify every dataset and both modes before collecting any measured samples.
    datasets, compiled = [], {}
    for name, rows in sizes:
        directory = data_dir / name
        path = directory / "data.csv"
        generate(path, rows)
        (directory / "program.dl").write_text(SOURCE, encoding="utf-8")
        expected, selected = expected_result(rows)
        baseline = None
        for optimized in (False, True):
            ir, _ = compile_program(directory, optimized)
            engine = ExecutionEngine(optimize=optimized)
            engine.execute(ir)
            verify(engine, rows)
            if baseline is not None:
                for table in baseline.tables:
                    pd.testing.assert_frame_equal(baseline.tables[table], engine.tables[table])
            else:
                baseline = engine
            compiled[name, optimized] = ir
        datasets.append({
            "name": name, "rows": rows, "csv_bytes": path.stat().st_size,
            "csv_sha256": digest(path), "directory": str(directory.resolve()),
            "expected_rows": expected, "expected_selected_rows": selected,
            "preflight": "passed in both modes; every intermediate table equivalent",
        })
    # Release preflight frames before measuring; IR contains no loaded data.
    del baseline, engine
    results = []
    for dataset in datasets:
        name, rows = dataset["name"], dataset["rows"]
        directory = Path(dataset["directory"])
        for _ in range(warmups):
            for optimized in (False, True):
                ir, _ = compile_program(directory, optimized)
                engine = ExecutionEngine(optimize=optimized)
                engine.execute(ir)
                verify(engine, rows)
                del engine
        samples = {False: [], True: []}
        for repetition in range(repetitions):
            # Alternate off/on and on/off to reduce systematic order bias.
            for position, optimized in enumerate((False, True) if repetition % 2 == 0 else (True, False)):
                ir, metrics = compile_program(directory, optimized)
                # Execute the preflight-checked IR. Construction, output checks,
                # summary statistics and report writing are outside this timer.
                engine = ExecutionEngine(optimize=optimized)
                begin = perf_counter_ns()
                engine.execute(compiled[name, optimized])
                metrics["execute_ns"] = perf_counter_ns() - begin
                verify(engine, rows)
                metrics.update(repetition=repetition + 1, position_in_pair=position + 1, correctness="passed")
                samples[optimized].append(metrics)
                del engine, ir
        for optimized in (False, True):
            results.append({**dataset, "optimized": optimized, "repetitions": repetitions,
                            "warmups": warmups, "samples": samples[optimized],
                            "summary": summarize(samples[optimized])})
        if digest(directory / "data.csv") != dataset["csv_sha256"]:
            raise AssertionError("Dataset changed during benchmarking")
    return results


def markdown(report):
    env = report["environment"]
    lines = ["# Executed DataLang benchmark", "", f"Recorded UTC: {report['recorded_at_utc']}", "",
             f"Python: {env['python'].splitlines()[0]}; pandas {env['pandas']}; NumPy {env['numpy']}.",
             f"OS: {env['os']}; CPU: {env['processor']}; logical CPUs: {env['logical_cpus']}.", "",
             "All datasets/modes passed preflight before measured samples. Every measured execution was checked again.",
             "Times below are measured medians in milliseconds; raw samples, ranges and sample standard deviations are in the JSON.", "",
             "| Size | Rows | Mode | Reps | Compile | Semantic total | Schema inspection (subset) | Execute |",
             "| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |"]
    for result in report["results"]:
        summary = result["summary"]
        times = [f"{summary[stage]['median_ns'] / 1e6:.3f}" for stage in (
            "compile_total_ns", "semantic_total_ns", "schema_inspection_ns", "execute_ns")]
        lines.append(f"| {result['name']} | {result['rows']:,} | {'on' if result['optimized'] else 'off'} | "
                     f"{result['repetitions']} | " + " | ".join(times) + " |")
    lines.extend(["", "One warmup per mode/size was used." if report["config"]["warmups"] == 1
                  else f"Warmups per mode/size: {report['config']['warmups']}.", "",
                  "Schema inspection is included in semantic and compilation totals; do not add it again.",
                  "Execution includes pandas CSV loading and all five IR operations. Source reading, imports, generation,",
                  "engine construction, correctness checks, printing and reporting are excluded. OS caches were not flushed;",
                  "preflight and warmups make this a warm-cache experiment, with cache residency uncontrolled.", "",
                  "These are observations for one machine and one workload. They do not establish a general optimization speedup.",
                  "See docs/benchmark.md for generation, oracle derivation and exact timing boundaries.", ""])
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, nargs=3, default=[rows for _, rows in SIZES],
                        metavar=("SMALL", "MEDIUM", "LARGER"))
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "benchmarks" / "generated")
    parser.add_argument("--output", type=Path, default=ROOT / "benchmarks" / "results" / "latest.json")
    args = parser.parse_args(argv)
    if args.repetitions < 2 or args.warmups < 0 or any(rows < 9 for rows in args.rows):
        parser.error("rows must be >=9, repetitions >=2 and warmups >=0")
    if args.rows != sorted(set(args.rows)):
        parser.error("row counts must be three distinct increasing sizes")
    report = {
        "status": "complete", "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "environment": environment(),
        "config": {"rows": args.rows, "repetitions": args.repetitions, "warmups": args.warmups,
                   "generator": "fixed nine-row pattern v1; no randomness", "source": SOURCE,
                   "source_sha256": hashlib.sha256(SOURCE.encode("utf-8")).hexdigest(),
                   "command": [sys.executable, "-B", "-m", "benchmarks.run_benchmark", *(argv if argv is not None else sys.argv[1:])],
                   "schema_inspection_is_subset": True, "cache_policy": "warm; OS cache not controlled"},
    }
    report["results"] = benchmark(args.data_dir, tuple(zip((name for name, _ in SIZES), args.rows)),
                                  args.repetitions, args.warmups)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    args.output.with_suffix(".md").write_text(markdown(report), encoding="utf-8")
    print(markdown(report))
    print(f"Raw results: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
