"""One UTF-8 JSON request on stdin, one JSON response on stdout; logs on stderr.

Launch from the repository root with ``python -u -m src.editor.bridge``.
This entry point uses only the Python standard library and the analysis layer.
"""

from __future__ import annotations

from contextlib import redirect_stdout
from dataclasses import asdict
import json
from pathlib import Path
import sys
import traceback
from typing import TextIO


PROTOCOL_VERSION = 1


def _validate(request: object) -> dict:
    if not isinstance(request, dict):
        raise ValueError("request must be a JSON object")
    if type(request.get("protocol_version")) is not int or request["protocol_version"] != PROTOCOL_VERSION:
        raise ValueError("protocol_version must be 1")
    for name in ("request_id", "document_uri", "document_path"):
        if not isinstance(request.get(name), str) or not request[name]:
            raise ValueError(f"{name} must be a nonempty string")
    if not Path(request["document_path"]).is_absolute():
        raise ValueError("document_path must be an absolute filesystem path")
    if not isinstance(request.get("text"), str):
        raise ValueError("text must be a string")
    version = request.get("document_version")
    if type(version) is not int or version < 0:
        raise ValueError("document_version must be a nonnegative integer")
    if not isinstance(request.get("method"), str) or request["method"] not in {"analyze", "cursor"}:
        raise ValueError("method must be 'analyze' or 'cursor'")
    if request["method"] == "cursor":
        position = request.get("position")
        if not isinstance(position, dict):
            raise ValueError("cursor requests require a position object")
        for name, minimum in (("line", 1), ("column", 0)):
            if type(position.get(name)) is not int or position[name] < minimum:
                raise ValueError(f"position.{name} must be an integer >= {minimum}")
    return request


def _analyze(request: dict) -> dict:
    from src.editor.analysis import analyze_document
    from src.editor.cursor import analyze_cursor

    args = (request["text"], request["document_path"], request["document_version"])
    if request["method"] == "analyze":
        return {"analysis": asdict(analyze_document(*args)), "cursor": None}
    position = request["position"]
    context = analyze_cursor(*args, position["line"], position["column"])
    cursor = asdict(context)
    cursor.pop("prefix")
    cursor["input_schema"] = asdict(context.input_schema) if context.input_schema else None
    return {"analysis": asdict(context.prefix), "cursor": cursor}


def serve(stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    """Read through EOF. Errors also produce exactly one JSON envelope."""
    request = None
    status = 0
    response = {"protocol_version": PROTOCOL_VERSION}
    try:
        request = json.load(stdin)
        request = _validate(request)
        # Reserve the protocol stream even if a lower analysis layer prints.
        with redirect_stdout(stderr):
            result = _analyze(request)
        response.update(ok=True, result=result)
    except (ValueError, UnicodeError) as error:
        status = 2
        response.update(ok=False, error={"code": "invalid_request", "message": str(error)})
        print(f"DataLang bridge: {error}", file=stderr)
    except Exception as error:
        status = 1
        response.update(ok=False, error={
            "code": "backend_error",
            "message": f"Analysis failed: {error}. Check the DataLang output log.",
        })
        traceback.print_exc(file=stderr)
    for name in ("request_id", "document_uri", "document_version"):
        value = request.get(name) if isinstance(request, dict) else None
        expected_type = int if name == "document_version" else str
        response[name] = value if type(value) is expected_type else None
    # JSON escapes also preserve lone UTF-16 surrogates from editor buffers,
    # which cannot be written as literal UTF-8 characters.
    stdout.write(json.dumps(response, ensure_ascii=True, allow_nan=False) + "\n")
    stdout.flush()
    return status


def main() -> int:
    for stream in (sys.stdin, sys.stdout):
        stream.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
    return serve(sys.stdin, sys.stdout, sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
