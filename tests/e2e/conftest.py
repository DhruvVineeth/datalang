"""Run the real driver and all stages; observe tables and render charts headlessly."""

from types import SimpleNamespace

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pytest

import src.main as driver
from src.executor import ExecutionEngine, VisualizationModule
from src.semantic.semantic import SemanticAnalyzer
from spec_oracles import FIXTURES


@pytest.fixture
def run_spec(monkeypatch, capsys):
    engines, analyzers, charts = [], [], []

    class Charts(VisualizationModule):
        def plot(self, table, chart_type, column):
            figure = super().plot(table, chart_type, column)
            charts.append((chart_type, column, table.copy(), figure))
            return figure

    class Engine(ExecutionEngine):
        def __init__(self):
            super().__init__(visualization=Charts(show=False))
            engines.append(self)

    class Analyzer(SemanticAnalyzer):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            analyzers.append(self)

    monkeypatch.setattr(driver, "ExecutionEngine", Engine)
    monkeypatch.setattr(driver, "SemanticAnalyzer", Analyzer)

    def run(source, directory=FIXTURES, **options):
        engines.clear()
        analyzers.clear()
        status = driver.compile_source(source, directory, **options)
        output = capsys.readouterr()
        return SimpleNamespace(status=status, stdout=output.out, stderr=output.err,
                               engine=engines[-1] if engines else None,
                               symbols=analyzers[-1].symbol_table if analyzers else None,
                               charts=charts)

    yield run
    for _, _, _, figure in charts:
        plt.close(figure)
