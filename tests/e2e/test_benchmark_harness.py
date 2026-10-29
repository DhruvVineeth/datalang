"""Small real harness runs validate instrumentation/reporting, not speed."""

import json

import pytest

import benchmarks.run_benchmark as runner
import src.semantic.semantic as semantic_module


def test_real_benchmark_records_disjoint_compile_phases_and_nested_schema_cost(tmp_path):
    results = runner.benchmark(tmp_path, sizes=(("tiny", 17),), repetitions=2, warmups=0)
    assert [result["optimized"] for result in results] == [False, True]
    for result in results:
        assert len(result["samples"]) == 2
        assert result["expected_selected_rows"] == 14
        assert result["csv_bytes"] > 0 and len(result["csv_sha256"]) == 64
        for sample in result["samples"]:
            assert sample["correctness"] == "passed"
            assert sample["schema_inspection_calls"] == 1
            assert 0 < sample["schema_inspection_ns"] <= sample["semantic_total_ns"]
            assert sample["compile_total_ns"] == sum(sample[stage] for stage in (
                "lex_ns", "parse_ns", "semantic_total_ns", "ir_ns", "optimize_ns"))
            assert sample["execute_ns"] > 0
    assert [sample["position_in_pair"] for sample in results[0]["samples"]] == [1, 2]
    assert [sample["position_in_pair"] for sample in results[1]["samples"]] == [2, 1]


def test_correctness_failure_prevents_measured_samples_and_restores_schema_hook(tmp_path, monkeypatch):
    original_inspect = semantic_module.inspect_csv_schema

    def fail(*args):
        raise AssertionError("oracle mismatch")

    def forbidden(*args):
        pytest.fail("Collected measured statistics despite failed preflight")

    monkeypatch.setattr(runner, "verify", fail)
    monkeypatch.setattr(runner, "summarize", forbidden)
    with pytest.raises(AssertionError, match="oracle mismatch"):
        runner.benchmark(tmp_path, sizes=(("tiny", 9),), repetitions=2, warmups=0)
    assert semantic_module.inspect_csv_schema is original_inspect


def test_main_writes_real_raw_samples_and_readable_summary(tmp_path, capsys):
    output = tmp_path / "results.json"
    assert runner.main(["--rows", "9", "10", "17", "--repetitions", "2", "--warmups", "0",
                        "--data-dir", str(tmp_path / "generated"), "--output", str(output)]) == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == "complete" and len(report["results"]) == 6
    assert report["config"]["rows"] == [9, 10, 17]
    assert "python" in report["environment"] and "source_sha256" in report["environment"]
    assert all(len(result["samples"]) == 2 for result in report["results"])
    assert "Schema inspection (subset)" in output.with_suffix(".md").read_text(encoding="utf-8")
    assert "Raw results:" in capsys.readouterr().out
