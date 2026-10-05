"""
DataLang symbol table.

Stores datasets, column names, and inferred data types. Semantic analysis
inserts a dataset after LOAD (once the CSV schema has been inspected) and
looks up columns while checking SELECT, FILTER, and PLOT/VISUALIZE.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple


# Data types from the architecture proposal's symbol-table example.
INTEGER = "Integer"
NUMERIC = "Numeric"
STRING = "String"
TABLE = "Table"

DATASET = "Dataset"
COLUMN = "Column"


@dataclass
class Symbol:
    """One entry in the symbol table."""

    name: str
    data_type: str
    symbol_type: str
    dataset: Optional[str] = None
    file_path: Optional[str] = None
    columns: Dict[str, "Symbol"] = field(default_factory=dict)


class SymbolTable:
    """
    Dataset-scoped symbol table.

    Datasets are top-level symbols. Each dataset holds a nested map of
    column symbols (name, inferred type, and owning dataset).
    """

    def __init__(self) -> None:
        self._datasets: Dict[str, Symbol] = {}

    def insert(self, symbol: Symbol) -> None:
        """Insert a dataset or column symbol."""
        if symbol.symbol_type == DATASET:
            self._datasets[symbol.name] = symbol
            return
        if symbol.symbol_type == COLUMN:
            if symbol.dataset is None:
                raise ValueError(f"Column '{symbol.name}' must belong to a dataset")
            dataset = self.lookup(symbol.dataset)
            if dataset is None or dataset.symbol_type != DATASET:
                raise KeyError(f"Dataset '{symbol.dataset}' is not in the symbol table")
            dataset.columns[symbol.name] = symbol
            return
        raise ValueError(f"Unknown symbol type: {symbol.symbol_type}")

    def lookup(self, name: str) -> Optional[Symbol]:
        """Look up a dataset by name."""
        return self._datasets.get(name)

    def lookup_column(self, dataset_name: str, column_name: str) -> Optional[Symbol]:
        """Look up a column inside a loaded dataset."""
        dataset = self.lookup(dataset_name)
        if dataset is None:
            return None
        return dataset.columns.get(column_name)

    def has_dataset(self, name: str) -> bool:
        """True if a dataset with this name has been inserted (i.e. loaded)."""
        return name in self._datasets

    def column_exists(self, dataset_name: str, column_name: str) -> bool:
        """True if the named column exists in the given dataset."""
        return self.lookup_column(dataset_name, column_name) is not None

    def insert_dataset(
        self,
        name: str,
        file_path: str,
        columns: Dict[str, str],
    ) -> Symbol:
        """
        Record a loaded dataset and its columns.

        Args:
            name: Dataset identifier from LOAD ... AS <identifier>
            file_path: CSV path that was inspected
            columns: Mapping of column name -> inferred data type
        """
        dataset = Symbol(
            name=name,
            data_type=TABLE,
            symbol_type=DATASET,
            file_path=file_path,
        )
        self.insert(dataset)
        for column_name, data_type in columns.items():
            self.insert(
                Symbol(
                    name=column_name,
                    data_type=data_type,
                    symbol_type=COLUMN,
                    dataset=name,
                )
            )
        return dataset

    def datasets(self) -> Iterator[Symbol]:
        """Iterate over loaded dataset symbols."""
        return iter(self._datasets.values())

    def all_symbols(self) -> List[Symbol]:
        """Flat list of dataset symbols followed by their columns."""
        symbols: List[Symbol] = []
        for dataset in self._datasets.values():
            symbols.append(dataset)
            symbols.extend(dataset.columns.values())
        return symbols

    def format_table(self) -> str:
        """Render the symbol table in the proposal's Name / Data Type / Symbol Type layout."""
        rows = [("Name", "Data Type", "Symbol Type", "Dataset")]
        for symbol in self.all_symbols():
            rows.append(
                (
                    symbol.name,
                    symbol.data_type,
                    symbol.symbol_type,
                    symbol.dataset or "-",
                )
            )
        widths = [max(len(row[i]) for row in rows) for i in range(4)]
        lines = []
        for i, row in enumerate(rows):
            line = "  ".join(cell.ljust(widths[j]) for j, cell in enumerate(row))
            lines.append(line)
            if i == 0:
                lines.append("  ".join("-" * widths[j] for j in range(4)))
        return "\n".join(lines)


def is_numeric_type(data_type: str) -> bool:
    """Integer and Numeric are both numeric for FILTER/PLOT checks."""
    return data_type in (INTEGER, NUMERIC)


def _looks_like_int(text: str) -> bool:
    if text.startswith(("+", "-")):
        text = text[1:]
    return text.isdigit()


def _looks_like_float(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True


def infer_column_type(values: List[str]) -> str:
    """
    Infer a column's DataLang type from CSV cell strings.

    All integers -> Integer; all numbers (including mixed int/float) -> Numeric;
    otherwise -> String. Empty cells are ignored. An entirely empty column is String.
    """
    nonempty = [value.strip() for value in values if value is not None and value.strip() != ""]
    if not nonempty:
        return STRING
    if all(_looks_like_int(value) for value in nonempty):
        return INTEGER
    if all(_looks_like_float(value) for value in nonempty):
        return NUMERIC
    return STRING


def inspect_csv_schema(file_path: str) -> Tuple[Dict[str, str], List[str]]:
    """
    Read a CSV file and return (column_name -> inferred type, column order).

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file has no header row.
    """
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(str(path))

    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration as exc:
            raise ValueError(f"CSV file '{path}' is empty") from exc

        names = [name.strip() for name in header]
        if not names or all(name == "" for name in names):
            raise ValueError(f"CSV file '{path}' has no column headers")

        columns: Dict[str, List[str]] = {name: [] for name in names}
        for row in reader:
            for index, name in enumerate(names):
                cell = row[index] if index < len(row) else ""
                columns[name].append(cell)

    inferred = {name: infer_column_type(columns[name]) for name in names}
    return inferred, names
