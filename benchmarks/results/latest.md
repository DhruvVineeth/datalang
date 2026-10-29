# Executed DataLang benchmark

Recorded UTC: 2026-10-28T06:32:45.506056+00:00

Python: 3.11.9 (tags/v3.11.9:de54cf5, Apr  2 2024, 10:12:12) [MSC v.1938 64 bit (AMD64)]; pandas 3.0.5; NumPy 2.3.4.
OS: Windows-10-10.0.26200-SP0; CPU: AMD64 Family 25 Model 68 Stepping 1, AuthenticAMD; logical CPUs: 16.

All datasets/modes passed preflight before measured samples. Every measured execution was checked again.
Times below are measured medians in milliseconds; raw samples, ranges and sample standard deviations are in the JSON.

| Size | Rows | Mode | Reps | Compile | Semantic total | Schema inspection (subset) | Execute |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| small | 1,000 | off | 5 | 3.629 | 3.188 | 2.502 | 5.349 |
| small | 1,000 | on | 5 | 3.727 | 3.213 | 2.575 | 5.823 |
| medium | 10,000 | off | 5 | 25.883 | 25.269 | 24.569 | 11.798 |
| medium | 10,000 | on | 5 | 26.195 | 25.674 | 25.039 | 11.474 |
| larger | 100,000 | off | 5 | 246.595 | 245.881 | 245.159 | 56.088 |
| larger | 100,000 | on | 5 | 248.492 | 247.959 | 247.241 | 55.964 |

One warmup per mode/size was used.

Schema inspection is included in semantic and compilation totals; do not add it again.
Execution includes pandas CSV loading and all five IR operations. Source reading, imports, generation,
engine construction, correctness checks, printing and reporting are excluded. OS caches were not flushed;
preflight and warmups make this a warm-cache experiment, with cache residency uncontrolled.

These are observations for one machine and one workload. They do not establish a general optimization speedup.
See docs/benchmark.md for generation, oracle derivation and exact timing boundaries.
