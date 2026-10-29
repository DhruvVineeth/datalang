# Reproducible DataLang benchmark

Run from the repository root, using the existing pandas/matplotlib dependencies:

```powershell
python -B -m benchmarks.run_benchmark --rows 1000 10000 100000 --repetitions 5 --warmups 1
```

This writes deterministic CSVs and `.dl` programs under `benchmarks/generated/`
(ignored by Git), raw samples/environment to `benchmarks/results/latest.json`,
and a readable measured-results table to `benchmarks/results/latest.md`.
`--data-dir` and `--output` select alternative locations; `--rows` requires three
distinct increasing sizes, each at least nine. Regeneration overwrites only the
named benchmark input files. No additional package is required by the benchmark.

## Workload and independent correctness

Each CSV repeats the nine rows documented in `specification-tests.md`, with a
new sequential row ID each time. Headers are row, group_key, amount, units.
Generation uses fixed literal values and no randomness; the generator is version
1. CSV line endings are LF, encoding UTF-8, delimiter comma. Row counts, byte
counts and SHA-256 hashes are saved. The program is fixed across sizes/modes:

```text
LOAD "data.csv" AS data;
SELECT group_key, amount, units FROM data;
FILTER data WHERE NOT NOT units >= 1;
AGGREGATE SUM(amount) FROM data GROUP BY group_key;
SORT sum_amount DESC FROM data;
```

Only the two zero-unit positions in each cycle are filtered out. For a row count
`n = 9q + r`, the selected count is `7q + [0,1,1,2,3,4,5,6,7][r]`.
Expected sums use closed-form arithmetic rather than a pandas/compiler result:

- z: `8q + (9.5 if r>=1 else 0) - (1.5 if r>=3 else 0)`.
- Null key: `6q + (4 if r>=4 else 0) + (2 if r>=7 else 0)`.
- b: `-2q - (2 if r>=8 else 0)`.
- a: null, because its retained targets are all missing.

The final row order is z, null key, b, a, with ordered schema
`group_key:String, sum_amount:Numeric`, runtime dtypes string/Float64 and stable
source index `[0,1,3,2]`. For the default sizes the expected outputs are:

| Input rows | Filtered rows | z | Null key | b | a |
| ---: | ---: | ---: | ---: | ---: | --- |
| 1,000 | 778 | 897.5 | 666 | -222 | null |
| 10,000 | 7,778 | 8897.5 | 6666 | -2222 | null |
| 100,000 | 77,778 | 88897.5 | 66666 | -22222 | null |

Before collecting **any measured samples**, all sizes pass compilation, schema,
value, order, dtype, intermediate cardinality and final-binding checks in both
optimization modes. Every intermediate DataFrame is compared between modes.
Every warmup and measured execution is checked again outside its timer. A failed
check aborts the run; it cannot produce a new successful report. Input hashes
are checked again after timing each size to detect changes during the experiment.

## Exact timing boundaries

All durations are integer nanoseconds from `time.perf_counter_ns`. Imports,
interpreter startup, generation, hashing, `.dl` file reading, verification,
engine construction, output formatting and report writing are excluded. The
source program is already in memory when compilation starts.

| Metric | Starts | Stops | Included work |
| --- | --- | --- | --- |
| lex | Immediately before Lexer construction | After tokenization and lexical-error check | Token creation and scan |
| parse | Before Parser construction | After parse | AST creation |
| semantic total | Before SemanticAnalyzer construction | After analyze | CSV schema inspection, validation and schema updates |
| schema inspection | At each existing inspect_csv_schema call | Its return/exception | Full CSV read, cell collection and type inference; one call per compilation here |
| IR | Before IRGenerator construction | After generate | Checked AST lowering |
| optimize | Before optimize_ir | Its return | Hint pass on, immediate bypass off |
| compilation total | Start of lex | End of optimize | Sum of the five disjoint compilation phases |
| execution | Immediately before execute on a fresh, constructed engine | execute returns | State reset, pandas CSV loading and all five IR instructions |

**Schema inspection is a nested subset of semantic time and compilation time.**
Do not add it to either total. It is not reused across compilations: every sample
rereads the entire CSV for inference. Runtime LOAD rereads it with pandas and is
included in execution. CSV schema inspection can therefore dominate compilation
even though the source program has constant length. Its clock-wrapper overhead
is included and not subtracted; installing/restoring the wrapper is untimed.

Execution uses the IR compiled and checked during preflight; timed compilation
creates fresh IR independently each repetition. The normal semantic-analysis
stage is always used; the benchmark never executes parser output. No plotting
or console-result printing occurs in this workload.

## Sampling, environment and interpretation

Defaults are five measured repetitions **per size per mode**, after one untimed
warmup per mode/size. Optimization off/on and on/off alternate across repetition
pairs to reduce systematic ordering bias. All measurements use one process and
one Python driver thread; numerical libraries retain their recorded settings.
Automatic Python GC retains its existing setting; no manual collection
or cache flushing occurs. Correctness preflight and warmups have already read
each CSV: these are warm-cache measurements, with OS cache residency uncontrolled.

Reports record Python version/implementation/executable, OS, machine/processor,
logical CPUs, pandas/NumPy/matplotlib versions, GC setting, relevant thread/hash
environment variables, clock implementation/resolution, Git revision/working-tree
status and SHA-256 hashes of compiler sources and the benchmark script. This
captures uncommitted compiler changes; a Git revision alone would not identify
the measured code in this workspace. The source text, invocation and source hash
are included. Raw samples retain repetition and mode order. Summaries report
median, minimum, maximum and sample standard deviation for every metric.

Read [the executed report](../benchmarks/results/latest.md) alongside its
[raw JSON/environment](../benchmarks/results/latest.json). These measurements
describe one machine, dataset distribution and pipeline;
they do not establish a general optimization speedup or asymptotic complexity.
The small-input harness tests exercise correctness/instrumentation and are not
reported as performance experiments.

## Executed run

The recorded run used all three default sizes, five measured repetitions per
mode/size and one warmup: **30 measured executions passed correctness checks**.
Preflight also passed for every size/mode before measurements. At 100,000 rows,
median compilation was 246.595 ms off / 248.492 ms on, of which schema inspection
was 245.159 / 247.241 ms. Execution medians were 56.088 / 55.964 ms. The measured
on/off differences are inconsistent across sizes; this run does not demonstrate
a general optimization benefit. Consult the raw samples and standard deviations
before interpreting small differences. The full regression suite completed with
**616 passed**, including the independent oracle and harness tests.
