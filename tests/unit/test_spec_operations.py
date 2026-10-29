"""Backend units: literal values and schemas, without lexer/parser/compiler."""

import pandas as pd
import pytest

from src.executor import DataAnalysisModule
from spec_oracles import AGGREGATE_DTYPES, REDUCTIONS, ROWS, SCHEMA, SORTS


@pytest.fixture
def frame():
    return pd.DataFrame(ROWS, columns=[name for name, _ in SCHEMA])


def literal_rows(frame):
    return tuple(tuple(None if pd.isna(value) else value for value in row)
                 for row in frame.itertuples(index=False, name=None))


@pytest.mark.parametrize("case", REDUCTIONS, ids=lambda case: case.function)
@pytest.mark.parametrize("grouped", [False, True], ids=["global", "grouped"])
def test_reductions_have_independent_values_and_typed_schemas(frame, case, grouped):
    schema = {"Team": "String", case.output: case.logical_type} if grouped else {case.output: case.logical_type}
    result = DataAnalysisModule().aggregate(frame, case.function, "Amount", "Team" if grouped else None, schema)
    assert list(result.columns) == list(schema)
    assert literal_rows(result) == (case.groups if grouped else ((case.value,),))
    assert [str(result[name].dtype) for name in schema] == [AGGREGATE_DTYPES[kind] for kind in schema.values()]


@pytest.mark.parametrize("case", REDUCTIONS, ids=lambda case: case.function)
@pytest.mark.parametrize("grouped", [False, True], ids=["global", "grouped"])
def test_zero_rows_keep_declared_schema_and_correct_cardinality(frame, case, grouped):
    schema = {"Team": "String", case.output: case.logical_type} if grouped else {case.output: case.logical_type}
    result = DataAnalysisModule().aggregate(frame.iloc[:0], case.function, "Amount", "Team" if grouped else None, schema)
    expected = () if grouped else ((0 if case.function == "COUNT" else None,),)
    assert literal_rows(result) == expected
    assert list(result.columns) == list(schema)
    assert [str(result[name].dtype) for name in schema] == [AGGREGATE_DTYPES[kind] for kind in schema.values()]


@pytest.mark.parametrize("column,direction,ids", SORTS)
def test_stable_sort_full_rows_schema_index_and_source_preservation(frame, column, direction, ids):
    original = frame.copy(deep=True)
    result = DataAnalysisModule().sort(frame, column, direction == "ASC", dict(SCHEMA)[column])
    assert literal_rows(result) == tuple(ROWS[identifier - 1] for identifier in ids)
    assert list(result.index) == [identifier - 1 for identifier in ids]
    assert result.dtypes.equals(frame.dtypes)
    assert list(result.columns) == ["row", "Team", "Amount", "Units"]
    pd.testing.assert_frame_equal(frame, original)


def test_projection_order_duplicates_and_filter_missing_mask(frame):
    module = DataAnalysisModule()
    selected = module.select(frame, ["Team", "Amount", "Team"])
    assert list(selected.columns) == ["Team", "Amount", "Team"]
    assert literal_rows(selected) == tuple((team, amount, team) for _, team, amount, _ in ROWS)
    mask = pd.Series([True, pd.NA, False, True, False, False, False, False, False], dtype="boolean")
    filtered = module.filter(frame, mask)
    assert literal_rows(filtered) == (ROWS[0], ROWS[3])
    assert filtered.dtypes.equals(frame.dtypes)
    assert list(filtered.index) == [0, 3]
