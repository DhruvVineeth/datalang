"""Exercise the actual stdin/stdout protocol and its analysis-layer boundary."""

from io import StringIO
import json
from pathlib import Path
import subprocess
import sys

import pytest

from src.editor import bridge


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def bridge_request(tmp_path):
    (tmp_path / "semi;data.csv").write_text("label,amount\n\u00e9\U0001f600,2.5\n", encoding="utf-8")
    # The actual document contents must never be read by the bridge.
    document = tmp_path / "unsaved.dl"
    document.write_text("invalid on-disk contents", encoding="utf-8")
    return {
        "protocol_version": 1,
        "request_id": "bridge_request-17",
        "method": "analyze",
        "document_uri": document.as_uri(),
        "document_path": str(document),
        "document_version": 17,
        "text": 'LOAD "semi;data.csv" AS sales; SELECT label FROM sales;',
    }


def invoke(bridge_request):
    return subprocess.run(
        [sys.executable, "-B", "-u", "-m", "src.editor.bridge"],
        input=json.dumps(bridge_request), text=True, encoding="utf-8", capture_output=True,
        cwd=ROOT, timeout=10, check=False,
    )


def test_subprocess_returns_one_response_for_unsaved_text(bridge_request):
    process = invoke(bridge_request)
    assert process.returncode == 0 and process.stderr == ""
    assert len(process.stdout.splitlines()) == 1
    response = json.loads(process.stdout)
    assert response["ok"] and response["protocol_version"] == 1
    for name in ("request_id", "document_uri", "document_version"):
        assert response[name] == bridge_request[name]
    result = response["result"]
    assert result["cursor"] is None
    assert result["analysis"]["diagnostics"] == []
    assert result["analysis"]["document_version"] == 17
    assert result["analysis"]["datasets"][0]["columns"] == [{"name": "label", "data_type": "String"}]
    assert len(result["analysis"]["statements"]) == 2
    assert "text" not in result["analysis"]


def test_cursor_requests_include_incomplete_context_and_input_schema(bridge_request):
    bridge_request.update(method="cursor", text='LOAD "semi;data.csv" AS sales;\nSELECT  FROM sales;')
    bridge_request["position"] = {"line": 2, "column": 7}
    process = invoke(bridge_request)
    response = json.loads(process.stdout)
    assert process.returncode == 0 and response["ok"]
    cursor = response["result"]["cursor"]
    assert cursor["schema_reliable"]
    assert cursor["active_statement"]["dataset_name"] == "sales"
    assert cursor["input_schema"]["columns"] == [
        {"name": "label", "data_type": "String"}, {"name": "amount", "data_type": "Numeric"},
    ]
    assert len(response["result"]["analysis"]["statements"]) == 1


def test_source_errors_are_successful_analysis_responses(bridge_request):
    bridge_request["text"] = 'SELECT missing FROM missing;'
    response = json.loads(invoke(bridge_request).stdout)
    assert response["ok"]
    assert response["result"]["analysis"]["diagnostics"][0]["stage"] == "semantic"


def test_unicode_and_unpaired_editor_surrogates_remain_valid_json(bridge_request):
    bridge_request["text"] = "@ \U0001f600 \ud800"
    process = invoke(bridge_request)
    assert process.returncode == 0 and process.stderr == ""
    response = json.loads(process.stdout)
    assert response["ok"]
    assert len(response["result"]["analysis"]["diagnostics"]) == 3
    assert "\ud800" in response["result"]["analysis"]["diagnostics"][-1]["message"]


@pytest.mark.parametrize("field,value", [
    ("protocol_version", 2), ("protocol_version", True),
    ("document_version", True), ("document_version", -1), ("document_version", float("nan")),
    ("request_id", None), ("text", 123), ("document_path", "relative.dl"),
    ("method", "execute"), ("method", []),
])
def test_invalid_request_fields_return_one_json_error(bridge_request, field, value):
    bridge_request[field] = value
    process = invoke(bridge_request)
    response = json.loads(process.stdout)
    assert process.returncode == 2 and not response["ok"]
    assert response["error"]["code"] == "invalid_request"
    assert process.stderr.startswith("DataLang bridge:")
    assert len(process.stdout.splitlines()) == 1


@pytest.mark.parametrize("position", [None, {}, {"line": 1, "column": True}, {"line": 99, "column": 0}])
def test_invalid_cursor_positions_are_protocol_errors(bridge_request, position):
    bridge_request.update(method="cursor", position=position)
    response = json.loads(invoke(bridge_request).stdout)
    assert not response["ok"] and response["error"]["code"] == "invalid_request"


@pytest.mark.parametrize("text", ["", "not JSON", "{}\n{}", "[]"])
def test_malformed_or_multiple_requests_still_produce_one_response(text):
    stdout, stderr = StringIO(), StringIO()
    assert bridge.serve(StringIO(text), stdout, stderr) == 2
    response = json.loads(stdout.getvalue())
    assert response["ok"] is False and response["request_id"] is None
    assert len(stdout.getvalue().splitlines()) == 1


def test_analyzer_prints_are_redirected_to_stderr(bridge_request, monkeypatch):
    original = bridge._analyze

    def noisy_analysis(value):
        print("backend debug log")
        return original(value)

    monkeypatch.setattr(bridge, "_analyze", noisy_analysis)
    stdout, stderr = StringIO(), StringIO()
    assert bridge.serve(StringIO(json.dumps(bridge_request)), stdout, stderr) == 0
    assert json.loads(stdout.getvalue())["ok"]
    assert stderr.getvalue() == "backend debug log\n"


def test_internal_errors_keep_tracebacks_off_stdout(bridge_request, monkeypatch):
    def failure(value):
        raise RuntimeError("injected failure")

    monkeypatch.setattr(bridge, "_analyze", failure)
    stdout, stderr = StringIO(), StringIO()
    assert bridge.serve(StringIO(json.dumps(bridge_request)), stdout, stderr) == 1
    assert json.loads(stdout.getvalue())["error"]["code"] == "backend_error"
    assert "Traceback" in stderr.getvalue() and "injected failure" in stderr.getvalue()
    assert "Traceback" not in stdout.getvalue()


def test_shell_metacharacters_are_only_document_data(bridge_request, tmp_path):
    marker = tmp_path / "should-not-exist"
    bridge_request["text"] += f'\n# `touch {marker}` $(touch {marker}); & echo unsafe\n'
    assert json.loads(invoke(bridge_request).stdout)["ok"]
    assert not marker.exists()
