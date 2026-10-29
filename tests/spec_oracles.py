"""Literal specification oracles. No compiler/backend imports or data reductions.

Arithmetic and ordering derivations: docs/specification-tests.md.
These constants are expected results, not execution records.
"""

from dataclasses import dataclass
from pathlib import Path


FIXTURES = Path(__file__).parent / "fixtures" / "specification"
SCHEMA = (("row", "Integer"), ("Team", "String"), ("Amount", "Numeric"), ("Units", "Integer"))
ROWS = (
    (1, "z", 9.5, 2), (2, "a", None, 0), (3, "z", -1.5, 3),
    (4, None, 4.0, 1), (5, "a", None, 4), (6, "b", 0.0, 2),
    (7, None, 2.0, 1), (8, "b", -2.0, 2), (9, "c", 8.0, 0),
)


@dataclass(frozen=True)
class Reduction:
    function: str
    output: str
    logical_type: str
    value: object
    groups: tuple


REDUCTIONS = (
    Reduction("SUM", "sum_Amount", "Numeric", 20.0,
              (("z", 8.0), ("a", None), (None, 6.0), ("b", -2.0), ("c", 8.0))),
    Reduction("AVG", "avg_Amount", "Numeric", 2.857142857142857,
              (("z", 4.0), ("a", None), (None, 3.0), ("b", -1.0), ("c", 8.0))),
    Reduction("COUNT", "count_Amount", "Integer", 7,
              (("z", 2), ("a", 0), (None, 2), ("b", 2), ("c", 1))),
    Reduction("MIN", "min_Amount", "Numeric", -2.0,
              (("z", -1.5), ("a", None), (None, 2.0), ("b", -2.0), ("c", 8.0))),
    Reduction("MAX", "max_Amount", "Numeric", 9.5,
              (("z", 9.5), ("a", None), (None, 4.0), ("b", 0.0), ("c", 8.0))),
)

# Explicit source row numbers; never calculated with the implementation's sorter.
SORTS = (
    ("Amount", "ASC", (8, 3, 6, 7, 4, 9, 1, 2, 5)),
    ("Amount", "DESC", (1, 9, 4, 7, 6, 3, 8, 2, 5)),
    ("Team", "ASC", (2, 5, 6, 8, 9, 1, 3, 4, 7)),
    ("Team", "DESC", (1, 3, 9, 6, 8, 2, 5, 4, 7)),
    ("Units", "ASC", (2, 9, 4, 7, 1, 6, 8, 3, 5)),
)

# The public language contract fixes logical schema; only aggregate outputs
# additionally promise explicit nullable runtime dtypes.
AGGREGATE_DTYPES = {"Integer": "Int64", "Numeric": "Float64", "String": "string"}
