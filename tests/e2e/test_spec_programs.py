"""Complete driver -> lexer -> parser -> semantic -> IR -> execution contracts."""

import pandas as pd
import pytest

from spec_oracles import AGGREGATE_DTYPES, REDUCTIONS, ROWS, SCHEMA, SORTS


LOAD = 'LOAD "orders.csv" AS orders;\n'


def assert_output(run, schema, rows, dataset="orders"):
    assert run.status == 0, run.stdout
    assert run.stderr == ""
    frame = run.engine.tables[run.engine.bindings[dataset]]
    assert list(frame.columns) == [name for name, _ in schema]
    actual = tuple(tuple(None if pd.isna(value) else value for value in row)
                   for row in frame.itertuples(index=False, name=None))
    assert actual == rows
    symbol = run.symbols.lookup(dataset)
    assert [(name, symbol.columns[name].data_type) for name in symbol.column_order] == list(schema)
    return frame


@pytest.mark.parametrize("case", REDUCTIONS, ids=lambda case: case.function)
@pytest.mark.parametrize("grouped", [False, True], ids=["global", "grouped"])
def test_aggregate_value_schema_names_and_group_encounter_order(run_spec, case, grouped):
    grouping = " GROUP BY Team" if grouped else ""
    run = run_spec(LOAD + f"AGGREGATE {case.function}(Amount) FROM orders{grouping};")
    schema = (("Team", "String"), (case.output, case.logical_type)) if grouped else ((case.output, case.logical_type),)
    frame = assert_output(run, schema, case.groups if grouped else ((case.value,),))
    assert str(frame[case.output].dtype) == AGGREGATE_DTYPES[case.logical_type]
    assert run.engine.last_output == "T2"


@pytest.mark.parametrize("case", REDUCTIONS, ids=lambda case: case.function)
@pytest.mark.parametrize("grouped", [False, True], ids=["global", "grouped"])
def test_filtered_empty_numeric_input_has_specified_schema_and_cardinality(run_spec, case, grouped):
    grouping = " GROUP BY Team" if grouped else ""
    run = run_spec(LOAD + f"FILTER orders WHERE row > 9; AGGREGATE {case.function}(Amount) FROM orders{grouping};")
    schema = (("Team", "String"), (case.output, case.logical_type)) if grouped else ((case.output, case.logical_type),)
    expected = () if grouped else ((0 if case.function == "COUNT" else None,),)
    frame = assert_output(run, schema, expected)
    assert str(frame[case.output].dtype) == AGGREGATE_DTYPES[case.logical_type]
    assert list(run.engine.tables["T2"].columns) == ["row", "Team", "Amount", "Units"]


@pytest.mark.parametrize("column,direction,ids", SORTS)
def test_sort_preserves_full_rows_schema_and_stable_missing_tail(run_spec, column, direction, ids):
    run = run_spec(LOAD + f"SORT {column} {direction} FROM orders;")
    result = assert_output(run, SCHEMA, tuple(ROWS[identifier - 1] for identifier in ids))
    assert result.dtypes.equals(run.engine.tables["T1"].dtypes)
    assert list(result.index) == [identifier - 1 for identifier in ids]
    assert list(run.engine.tables["T1"]["row"]) == [1, 2, 3, 4, 5, 6, 7, 8, 9]


@pytest.mark.parametrize("optimize", [False, True], ids=["optimization-off", "optimization-on"])
def test_multistage_pipeline_and_current_input_ties(run_spec, optimize):
    run = run_spec(LOAD + '''SELECT Units, Team FROM orders;
SORT Team DESC FROM orders;
FILTER orders WHERE NOT NOT Units >= 0;
AGGREGATE SUM(Units) FROM orders GROUP BY Team;
SORT sum_Units DESC FROM orders;''', optimize=optimize)
    frame = assert_output(run, (("Team", "String"), ("sum_Units", "Integer")),
                          (("z", 5), ("b", 4), ("a", 4), (None, 2), ("c", 0)))
    assert str(frame["sum_Units"].dtype) == "Int64"
    assert list(run.engine.tables) == ["T1", "T2", "T3", "T4", "T5", "T6"]
    assert run.engine.bindings == {"orders": "T6"}
    assert list(run.engine.tables["T2"].columns) == ["Units", "Team"]


def test_aggregate_of_aggregate_uses_unweighted_group_means(run_spec):
    run = run_spec(LOAD + '''AGGREGATE AVG(Amount) FROM orders GROUP BY Team;
AGGREGATE AVG(avg_Amount) FROM orders;''')
    assert_output(run, (("avg_avg_Amount", "Numeric"),), ((3.5,),))


def test_count_grouping_column_counts_present_values_and_keeps_null_group(run_spec):
    run = run_spec(LOAD + "AGGREGATE COUNT(Team) FROM orders GROUP BY Team;")
    assert_output(run, (("Team", "String"), ("count_Team", "Integer")),
                  (("z", 2), ("a", 2), (None, 0), ("b", 2), ("c", 1)))


def test_case_insensitive_keywords_and_independent_dataset_schemas(run_spec):
    run = run_spec('''load "orders.csv" as Orders;
LOAD "orders.csv" AS orders;
select Team, Amount from Orders;
aggregate SUM(Amount) from Orders group by Team;
FILTER orders WHERE row == 4;
SORT sum_Amount DESC FROM Orders;''')
    assert_output(run, SCHEMA, (ROWS[3],), dataset="orders")
    assert_output(run, (("Team", "String"), ("sum_Amount", "Numeric")),
                  (("z", 8.0), ("c", 8.0), (None, 6.0), ("b", -2.0), ("a", None)), dataset="Orders")
    assert run.engine.bindings == {"Orders": "T6", "orders": "T5"}


@pytest.mark.parametrize("operator,ids", [
    ("==", (1, 6, 8)), ("!=", (2, 3, 4, 5, 7, 9)), ("<", (2, 9)),
    ("<=", (2, 4, 7, 9)), (">", (1, 3, 5, 6, 8)), (">=", (1, 3, 4, 5, 6, 7, 8)),
])
def test_relational_filter_values_and_schema_preservation(run_spec, operator, ids):
    run = run_spec(LOAD + f"FILTER orders WHERE Units {operator} 2;" if operator in ("==", "!=")
                   else LOAD + f"FILTER orders WHERE Units {operator} 1;")
    assert_output(run, SCHEMA, tuple(ROWS[identifier - 1] for identifier in ids))


def test_not_and_or_precedence_preserves_input_row_order(run_spec):
    run = run_spec(LOAD + 'FILTER orders WHERE Team == "z" OR Amount >= 4 AND NOT Units == 0;')
    assert_output(run, SCHEMA, (ROWS[0], ROWS[2], ROWS[3]))


@pytest.mark.parametrize("chart", ["BAR", "LINE", "SCATTER"])
def test_real_plot_values_positions_and_category_order_after_pipeline(run_spec, chart):
    column = "Team" if chart == "BAR" else "Amount"
    run = run_spec(LOAD + f'''FILTER orders WHERE row <= 7;
SORT row DESC FROM orders;
VISUALIZE {chart} OF {column} FROM orders;''')
    expected_rows = (ROWS[6], ROWS[5], ROWS[4], ROWS[3], ROWS[2], ROWS[1], ROWS[0])
    assert_output(run, SCHEMA, expected_rows)
    assert len(run.charts) == 1
    kind, actual_column, _, figure = run.charts[0]
    assert (kind, actual_column) == (chart, column)
    axes = figure.axes[0]
    if chart == "BAR":
        assert [label.get_text() for label in axes.get_xticklabels()] == ["b", "a", "z"]
        assert [bar.get_height() for bar in axes.patches] == [1, 2, 2]
    elif chart == "LINE":
        assert list(axes.lines[0].get_xdata()) == [0, 1, 3, 4, 6]
        assert list(axes.lines[0].get_ydata()) == [2.0, 0.0, 4.0, -1.5, 9.5]
    else:
        assert axes.collections[0].get_offsets().tolist() == [[0, 2.0], [1, 0.0], [3, 4.0], [4, -1.5], [6, 9.5]]
    figure.canvas.draw()
