"""Schema contracts, transactional validation, actual tables and dataset isolation."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.executor import ExecutionEngine
from src.interpreter.ir import IRGenerator
from src.lexer.lexer import Lexer
from src.main import compile_source
from src.parser.parser import Parser
from src.semantic.semantic import SemanticAnalysisError, SemanticAnalyzer
from src.symbol_table.symbol_table import INTEGER, NUMERIC, STRING, SymbolTable


FIXTURES = Path(__file__).parent / "fixtures" / "phase3"
ORIGINAL = [("id", INTEGER), ("product", STRING), ("revenue", NUMERIC), ("quantity", INTEGER)]
PROJECTED = [("product", STRING), ("revenue", NUMERIC)]
GROUPED = [("product", STRING), ("sum_revenue", NUMERIC)]


def parse(source):
    return Parser(Lexer(source).tokenize()).parse()


def analyze(source):
    program = parse(source)
    analyzer = SemanticAnalyzer(FIXTURES)
    return program, analyzer.analyze(program)


def assert_schema(symbols, dataset, fields):
    entry = symbols.lookup(dataset)
    assert entry.column_order == [name for name, _ in fields]
    assert {name: column.data_type for name, column in entry.columns.items()} == dict(fields)
    assert all(column.dataset == dataset for column in entry.columns.values())


def execute(source):
    program, symbols = analyze(source)
    engine = ExecutionEngine()
    engine.execute(IRGenerator(symbols).generate(program))
    return symbols, engine


@pytest.mark.parametrize("tail,fields", [
    ("", ORIGINAL),
    ("SELECT revenue, product FROM sales;", list(reversed(PROJECTED))),
    ("SELECT product, revenue FROM sales; FILTER sales WHERE revenue >= 5;", PROJECTED),
    ("SELECT product, revenue FROM sales; SORT revenue DESC FROM sales;", PROJECTED),
    ("SELECT product, revenue FROM sales; FILTER sales WHERE revenue >= 5; SORT product FROM sales;", PROJECTED),
    ("SELECT product, revenue FROM sales; AGGREGATE SUM(revenue) FROM sales GROUP BY product;", GROUPED),
    ("AGGREGATE SUM(revenue) FROM sales GROUP BY product; FILTER sales WHERE sum_revenue > 0; SORT sum_revenue DESC FROM sales;", GROUPED),
    ("AGGREGATE SUM(revenue) FROM sales GROUP BY product; SELECT sum_revenue FROM sales;", [("sum_revenue", NUMERIC)]),
    ("AGGREGATE SUM(revenue) FROM sales GROUP BY product; AGGREGATE AVG(sum_revenue) FROM sales;", [("avg_sum_revenue", NUMERIC)]),
    ("FILTER sales WHERE id > 100; SELECT product, revenue FROM sales; SORT revenue FROM sales;", PROJECTED),
    ("FILTER sales WHERE id > 100; AGGREGATE COUNT(revenue) FROM sales GROUP BY product; SORT count_revenue FROM sales;", [("product", STRING), ("count_revenue", INTEGER)]),
])
def test_valid_pipeline_schema_matches_actual_output(tail, fields):
    symbols, engine = execute('LOAD "normal.csv" AS sales; ' + tail)
    assert_schema(symbols, "sales", fields)
    assert list(engine.result().columns) == [name for name, _ in fields]
    assert engine.bindings["sales"] == engine.last_output
    assert symbols.lookup("sales").file_path == str((FIXTURES / "normal.csv").resolve())


def test_each_pipeline_prefix_has_its_own_input_and_output_schema():
    steps = [
        ('LOAD "normal.csv" AS sales;', ORIGINAL),
        ("SELECT revenue, product FROM sales;", list(reversed(PROJECTED))),
        ("FILTER sales WHERE revenue >= 5;", list(reversed(PROJECTED))),
        ("SORT revenue DESC FROM sales;", list(reversed(PROJECTED))),
        ("AGGREGATE SUM(revenue) FROM sales GROUP BY product;", GROUPED),
        ("FILTER sales WHERE sum_revenue > 0;", GROUPED),
        ("SELECT sum_revenue FROM sales;", [("sum_revenue", NUMERIC)]),
        ("SORT sum_revenue FROM sales;", [("sum_revenue", NUMERIC)]),
        ("AGGREGATE COUNT(sum_revenue) FROM sales;", [("count_sum_revenue", INTEGER)]),
    ]
    source = ""
    for statement, fields in steps:
        source += statement + "\n"
        symbols, engine = execute(source)
        assert_schema(symbols, "sales", fields)
        assert list(engine.result().columns) == [name for name, _ in fields]


@pytest.mark.parametrize("prefix,invalid,fields", [
    ("", "SELECT product, missing FROM sales;", ORIGINAL),
    ("", "FILTER sales WHERE product > 1;", ORIGINAL),
    ("", 'FILTER sales WHERE revenue > 1 AND product == 1;', ORIGINAL),
    ("", "SORT missing FROM sales;", ORIGINAL),
    ("", "AGGREGATE SUM(product) FROM sales;", ORIGINAL),
    ("", "AGGREGATE SUM(revenue) FROM sales GROUP BY missing;", ORIGINAL),
    ("SELECT product, revenue FROM sales;", "SELECT quantity FROM sales;", PROJECTED),
    ("SELECT product, revenue FROM sales;", "FILTER sales WHERE quantity > 0;", PROJECTED),
    ("SELECT product, revenue FROM sales;", "SORT quantity FROM sales;", PROJECTED),
    ("SELECT product, revenue FROM sales;", "AGGREGATE SUM(quantity) FROM sales;", PROJECTED),
    ("SELECT revenue FROM sales;", "AGGREGATE SUM(revenue) FROM sales GROUP BY product;", [("revenue", NUMERIC)]),
    ("AGGREGATE SUM(revenue) FROM sales GROUP BY product;", "SELECT revenue FROM sales;", GROUPED),
    ("AGGREGATE SUM(revenue) FROM sales GROUP BY product;", "FILTER sales WHERE revenue > 0;", GROUPED),
    ("AGGREGATE SUM(revenue) FROM sales GROUP BY product;", "SORT revenue FROM sales;", GROUPED),
    ("AGGREGATE SUM(revenue) FROM sales GROUP BY product;", "AGGREGATE SUM(revenue) FROM sales;", GROUPED),
    ("AGGREGATE SUM(revenue) FROM sales GROUP BY product;", "VISUALIZE LINE OF revenue FROM sales;", GROUPED),
    ("AGGREGATE SUM(revenue) FROM sales GROUP BY product;", 'FILTER sales WHERE sum_revenue == "text";', GROUPED),
    ("AGGREGATE COUNT(product) FROM sales;", 'FILTER sales WHERE count_product == "two";', [("count_product", INTEGER)]),
])
def test_failed_validation_keeps_last_successful_schema(prefix, invalid, fields):
    program = parse('LOAD "normal.csv" AS sales; ' + prefix + invalid)
    analyzer = SemanticAnalyzer(FIXTURES)
    with pytest.raises(SemanticAnalysisError) as failure:
        analyzer.analyze(program)
    assert failure.value.errors
    assert_schema(analyzer.symbol_table, "sales", fields)
    assert id(program.statements[-1]) not in analyzer.symbol_table.statement_schemas


def test_name_collision_does_not_replace_dataset_schema():
    program = parse('LOAD "collision.csv" AS sales; AGGREGATE SUM(revenue) FROM sales GROUP BY sum_revenue;')
    analyzer = SemanticAnalyzer(FIXTURES)
    with pytest.raises(SemanticAnalysisError, match="conflicts"):
        analyzer.analyze(program)
    assert_schema(analyzer.symbol_table, "sales", [("id", INTEGER), ("sum_revenue", STRING), ("revenue", INTEGER)])


def test_failed_select_does_not_cause_errors_in_later_valid_statements():
    source = '''LOAD "normal.csv" AS sales;
SELECT product, missing FROM sales;
FILTER sales WHERE quantity > 0;
AGGREGATE SUM(quantity) FROM sales;
SORT sum_quantity FROM sales;'''
    analyzer = SemanticAnalyzer(FIXTURES)
    with pytest.raises(SemanticAnalysisError) as failure:
        analyzer.analyze(parse(source))
    assert len(failure.value.errors) == 1
    assert "missing" in failure.value.errors[0].message
    assert_schema(analyzer.symbol_table, "sales", [("sum_quantity", INTEGER)])


def test_dataset_isolation_for_same_file_and_overlapping_names():
    source = '''LOAD "normal.csv" AS left;
LOAD "normal.csv" AS right;
SELECT product, revenue FROM left;
FILTER left WHERE revenue >= 5;
AGGREGATE SUM(revenue) FROM left GROUP BY product;
SORT sum_revenue DESC FROM left;
SELECT quantity, revenue FROM right;
FILTER right WHERE quantity >= 2;
SORT revenue FROM right;'''
    symbols, engine = execute(source)
    assert_schema(symbols, "left", GROUPED)
    assert_schema(symbols, "right", [("quantity", INTEGER), ("revenue", NUMERIC)])
    assert symbols.lookup("left").columns is not symbols.lookup("right").columns
    assert engine.bindings == {"left": "T6", "right": "T9"}
    assert list(engine.tables["T6"]["product"]) == ["B", "A"]
    assert list(engine.tables["T6"]["sum_revenue"]) == [17.5, 17.5]
    assert list(engine.tables["T9"]["revenue"]) == [5, 10, 12.5]
    assert list(engine.tables["T1"].columns) == list(engine.tables["T2"].columns) == [name for name, _ in ORIGINAL]


def test_types_and_validation_are_scoped_to_the_named_dataset():
    source = '''LOAD "normal.csv" AS numeric_data;
LOAD "mixed.csv" AS text_data;
AGGREGATE SUM(revenue) FROM numeric_data;
FILTER text_data WHERE revenue == "oops";
AGGREGATE COUNT(revenue) FROM text_data;'''
    symbols, engine = execute(source)
    assert_schema(symbols, "numeric_data", [("sum_revenue", NUMERIC)])
    assert_schema(symbols, "text_data", [("count_revenue", INTEGER)])
    assert engine.tables[engine.bindings["numeric_data"]]["sum_revenue"].tolist() == [30]
    assert engine.result()["count_revenue"].tolist() == [1]
    with pytest.raises(SemanticAnalysisError, match="requires a numeric column"):
        analyze('LOAD "normal.csv" AS numeric_data; LOAD "mixed.csv" AS text_data; AGGREGATE SUM(revenue) FROM text_data;')


@pytest.mark.parametrize("fragment", [
    "SELECT missing FROM left;", "FILTER left WHERE product > 1;",
    "SORT missing FROM left;", "AGGREGATE SUM(product) FROM left;",
])
def test_failed_statement_isolated_from_other_dataset(fragment):
    source = f'''LOAD "normal.csv" AS left;
LOAD "mixed.csv" AS right;
{fragment}
SELECT revenue FROM right;'''
    analyzer = SemanticAnalyzer(FIXTURES)
    with pytest.raises(SemanticAnalysisError) as failure:
        analyzer.analyze(parse(source))
    assert len(failure.value.errors) == 1
    assert_schema(analyzer.symbol_table, "left", ORIGINAL)
    assert_schema(analyzer.symbol_table, "right", [("revenue", STRING)])


def test_duplicate_load_does_not_overwrite_existing_dataset():
    analyzer = SemanticAnalyzer(FIXTURES)
    with pytest.raises(SemanticAnalysisError, match="already loaded"):
        analyzer.analyze(parse('LOAD "normal.csv" AS sales; LOAD "mixed.csv" AS sales;'))
    assert_schema(analyzer.symbol_table, "sales", ORIGINAL)
    assert analyzer.symbol_table.lookup("sales").file_path == str((FIXTURES / "normal.csv").resolve())


def test_failed_load_does_not_create_partial_schema():
    analyzer = SemanticAnalyzer(FIXTURES)
    with pytest.raises(SemanticAnalysisError, match="not found"):
        analyzer.analyze(parse('LOAD "normal.csv" AS sales; LOAD "not-a-fixture.csv" AS missing;'))
    assert_schema(analyzer.symbol_table, "sales", ORIGINAL)
    assert not analyzer.symbol_table.has_dataset("missing")


def test_generated_numeric_type_can_be_aggregated_after_string_count():
    symbols, engine = execute('''LOAD "mixed.csv" AS sales;
AGGREGATE COUNT(revenue) FROM sales;
FILTER sales WHERE count_revenue > 0;
AGGREGATE SUM(count_revenue) FROM sales;''')
    assert_schema(symbols, "sales", [("sum_count_revenue", INTEGER)])
    assert engine.result()["sum_count_revenue"].tolist() == [2]


def test_dataset_names_remain_case_sensitive_and_isolated():
    symbols, engine = execute('''LOAD "normal.csv" AS Sales;
LOAD "mixed.csv" AS sales;
SELECT product FROM Sales;
AGGREGATE COUNT(revenue) FROM sales;''')
    assert_schema(symbols, "Sales", [("product", STRING)])
    assert_schema(symbols, "sales", [("count_revenue", INTEGER)])
    assert engine.bindings == {"Sales": "T3", "sales": "T4"}
    assert len(engine.tables["T3"]) == 6
    assert engine.result()["count_revenue"].tolist() == [2]


def test_repeated_projection_order_matches_runtime_and_remains_valid():
    source = '''LOAD "normal.csv" AS sales;
SELECT product, revenue, product FROM sales;
FILTER sales WHERE revenue >= 5;
SORT revenue FROM sales;
SELECT product, revenue FROM sales;'''
    symbols, engine = execute(source)
    assert_schema(symbols, "sales", [("product", STRING), ("product", STRING), ("revenue", NUMERIC)])
    assert list(engine.result().columns) == ["product", "product", "revenue"]
    assert engine.result().iloc[:, 0].tolist() == engine.result().iloc[:, 1].tolist() == ["B", "A", "A", "B"]
    assert engine.result()["revenue"].tolist() == [5, 7.5, 10, 12.5]


def test_reselecting_repeated_names_matches_runtime_expansion():
    symbols, engine = execute('''LOAD "normal.csv" AS sales;
SELECT product, product FROM sales;
SELECT product, product FROM sales;''')
    assert_schema(symbols, "sales", [("product", STRING)] * 4)
    assert list(engine.result().columns) == ["product"] * 4
    assert engine.result().iloc[0].tolist() == ["B"] * 4


def test_symbol_table_display_retains_repeated_field_order():
    _, symbols = analyze('LOAD "normal.csv" AS sales; SELECT revenue, product, revenue FROM sales;')
    assert [symbol.name for symbol in symbols.all_symbols()] == ["sales", "revenue", "product", "revenue"]


@pytest.mark.parametrize("operation", [
    'FILTER sales WHERE product == "A";', "SORT product FROM sales;",
    "AGGREGATE COUNT(product) FROM sales;", "AGGREGATE SUM(revenue) FROM sales GROUP BY product;",
    "VISUALIZE BAR OF product FROM sales;",
])
def test_ambiguous_scalar_column_references_fail_semantics(operation):
    analyzer = SemanticAnalyzer(FIXTURES)
    source = 'LOAD "normal.csv" AS sales; SELECT product, product, revenue FROM sales; ' + operation
    with pytest.raises(SemanticAnalysisError, match="product.*ambiguous"):
        analyzer.analyze(parse(source))
    assert_schema(analyzer.symbol_table, "sales", [("product", STRING), ("product", STRING), ("revenue", NUMERIC)])


def test_aggregate_can_drop_unreferenced_duplicate_fields():
    symbols, engine = execute('''LOAD "normal.csv" AS sales;
SELECT product, product, revenue FROM sales;
AGGREGATE SUM(revenue) FROM sales;''')
    assert_schema(symbols, "sales", [("sum_revenue", NUMERIC)])
    assert engine.result()["sum_revenue"].tolist() == [30]


def test_invalid_schema_replacement_is_atomic():
    table = SymbolTable()
    table.insert_dataset("sales", "data.csv", {"product": STRING, "revenue": NUMERIC})
    with pytest.raises(ValueError, match="Column order"):
        table.replace_columns("sales", {"product": STRING}, ["revenue"])
    assert_schema(table, "sales", PROJECTED)


@pytest.mark.parametrize("invalid", [
    "SELECT missing FROM sales;", "FILTER sales WHERE quantity > 0;",
    "SORT quantity FROM sales;", "AGGREGATE SUM(quantity) FROM sales;",
    "VISUALIZE LINE OF quantity FROM sales;",
])
def test_invalid_current_schema_never_reaches_ir_or_runtime(monkeypatch, capsys, invalid):
    def forbidden(*args, **kwargs):
        raise AssertionError("Schema-invalid source reached a later stage")
    monkeypatch.setattr("src.main.IRGenerator.generate", forbidden)
    monkeypatch.setattr("src.main.ExecutionEngine.execute", forbidden)
    source = 'LOAD "normal.csv" AS sales; SELECT product, revenue FROM sales; ' + invalid
    assert compile_source(source, FIXTURES) == 1
    assert "Semantic error at line 1, column" in capsys.readouterr().out
