"""Make repository and independent specification oracles importable in both tiers."""

import sys
from pathlib import Path

TESTS = Path(__file__).resolve().parent
for directory in (TESTS.parent, TESTS):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))
