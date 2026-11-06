# DataLang for VS Code

Registers the language ID `datalang` for `.dl` files, with syntax highlighting,
`#` line-comment toggling, parenthesis matching, and automatic closing and
surrounding of parentheses and double quotes. A configured Python backend adds
live diagnostics for the current, unsaved editor text.

The TextMate grammar follows the implementation in
[`../src/lexer/lexer.py`](../src/lexer/lexer.py) and
[`../src/parser/parser.py`](../src/parser/parser.py):

- Case-insensitive statement and clause keywords, logical operators, aggregate
  functions (`SUM`, `AVG`, `COUNT`, `MIN`, `MAX`), and chart types.
- Contextual `SORT`, `ASC`, and `DESC` highlighting. These words remain identifiers
  in statements such as `SELECT asc, desc, sort FROM sort;`.
- Double-quoted strings, including multiline strings and the recognized escapes
  `\"`, `\\`, `\n`, `\t`, and `\r`. Unknown escapes are preserved by the lexer.
- Unsigned integers and decimal numbers, identifiers, `==`, `!=`, `<`, `>`, `<=`,
  `>=`, commas, parentheses, and semicolon statement terminators.

Use `==` for equality. The current lexer does not support bare `=`, single-quoted
strings, block comments, signed numbers, or exponent notation. `PIE` is highlighted
because the lexer and parser accept it, although semantic analysis rejects it.

## Settings

Open Settings and search for **DataLang**, or edit `settings.json`:

```json
{
  "datalang.pythonExecutable": "python",
  "datalang.backendPath": "",
  "datalang.analysisDebounceMs": 300,
  "datalang.analysisTimeoutMs": 10000
}
```

| Setting | Default | Meaning |
| --- | --- | --- |
| `datalang.pythonExecutable` | `"python"` | Executable on PATH or an absolute interpreter path, for example `C:/path/to/.venv/Scripts/python.exe`. Do not include arguments. |
| `datalang.backendPath` | `""` | Absolute DataLang repository root containing `src/lexer/lexer.py` and `src/parser/parser.py`. Empty leaves the backend unconfigured. |
| `datalang.analysisDebounceMs` | `300` | Milliseconds to wait after the last edit before analysis; integer from `0` to `60000`. `0` requests immediate analysis. |
| `datalang.analysisTimeoutMs` | `10000` | Request timeout including Python startup and CSV inspection; integer from `100` to `120000`. Timed-out processes are terminated. |

Executable and backend paths are machine-specific settings that can be overridden
per workspace or folder. The debounce setting can also vary per folder.

An empty backend path disables analysis. Python is not needed for highlighting.

## Install and configure the backend

The backend source is the DataLang repository, installed separately from the
extension. Keep the complete repository, including `src/editor/bridge.py`, on the
machine where the VS Code extension host runs. Use **Python 3.10 or newer**.
The analysis bridge and CSV schema inference use only the Python standard
library: they do not import Pandas, Matplotlib, or the execution engine.

For a full compiler installation, create a virtual environment in the repository
and install its runtime dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

On macOS/Linux use `.venv/bin/python` for the second command. The repository's
runtime requirements are `pandas>=1.5` and `matplotlib>=3.6`; these are needed for
compiler execution/plotting, but optional for editor analysis. Python tests also
require `pytest`, installed separately with `python -m pip install pytest`.
The extension never installs Python or packages automatically.

Set absolute paths, for example on Windows:

```json
{
  "datalang.pythonExecutable": "C:/projects/datalang/.venv/Scripts/python.exe",
  "datalang.backendPath": "C:/projects/datalang"
}
```

Supply a single executable, without quotes embedded in the setting or command
arguments such as `-m`, `-3`, or `wsl python`. Paths containing spaces work.
For Remote/WSL development, install/configure Python and the repository in the
extension host's environment, using that environment's filesystem paths.

Trust the workspace and open a `.dl` document to analyze it immediately. Edits are debounced per document
for 300 ms by default. Diagnostics appear in the editor and Problems panel.
Relative LOAD paths resolve from the document's directory. Untitled DataLang
buffers use the workspace folder as their relative-path base (or the backend
root when no folder is open). Their text is sent directly; no document is saved
or read from disk. Saving under a new URI starts fresh analysis.

Startup failures and timeouts show a clear notification. **View > Output >
DataLang** contains backend stderr and error details. Check the configured
interpreter and repository root first; increase the timeout for large/slow CSVs.
Repeated identical errors are notified once until the settings change.

## Workspace trust

Restricted Mode supports syntax highlighting and editor configuration. Python
backend execution requires a trusted workspace, since the interpreter and backend
location select code to execute. Workspace overrides of `datalang.pythonExecutable`
and `datalang.backendPath` are restricted until trust is granted.

The client checks `vscode.workspace.isTrusted` immediately before every spawn,
including when using user-level settings, and schedules analysis when trust is
granted. Restricted settings alone do not block process execution.
See the [VS Code Workspace Trust guide](https://code.visualstudio.com/api/extension-guides/workspace-trust).

## JSON protocol

Each request starts one process with the configured Python executable and the
argument array `['-u', '-m', 'src.editor.bridge']`, working in `backendPath`.
Shell execution is disabled, and document contents are never command arguments.
The extension writes one UTF-8 JSON object to stdin, then closes stdin. The backend
reads through EOF and writes exactly one JSON response to stdout. Logs and Python
tracebacks go to stderr. There is no persistent server or shared document state.

Example request (filesystem paths must be absolute in the backend environment):

```json
{
  "protocol_version": 1,
  "request_id": "example-1",
  "method": "analyze",
  "document_uri": "file:///projects/example.dl",
  "document_path": "/projects/example.dl",
  "document_version": 12,
  "text": "LOAD \"sales.csv\" AS sales;"
}
```

A successful envelope echoes `protocol_version`, `request_id`, `document_uri`,
and `document_version`, and has `ok: true` plus `result`. The result contains
`analysis` (diagnostics, dataset schemas, and immutable statement snapshots) and
`cursor: null`. Source errors are successful analysis responses with diagnostics.
Protocol/backend failures use `ok: false` and `error: {code, message}`; exit codes
are 0 for successful analysis, 2 for invalid requests, and 1 for internal errors.

The bridge also accepts `method: "cursor"` with `position: {line, column}`.
Positions use one-based lines and zero-based Python character columns. Its result
contains the checked prefix in `analysis` and the active statement, input schema,
grammar assistance, and reliability flag in `cursor`. The initial extension
publisher uses strict `analyze` requests. Diagnostics have `stage`, `message`,
`severity`, `line`, `column`, and optional exclusive `end_line`/`end_column`.
Identifier errors underline the exact reference, type mismatches underline the
incompatible literal or column, and CSV errors underline the quoted LOAD path.
The extension converts both endpoints to VS Code's zero-based UTF-16 positions,
including astral characters and combining marks. An editor position inside a
surrogate pair converts to the start of that code point. Legacy diagnostics
without an end select one code point; an unknown column selects the whole line.
Positions outside the document are clamped, and EOF may have an empty range.
See the [VS Code position API](https://code.visualstudio.com/api/references/vscode-api#Position).

Edits, document closure, and configuration changes cancel obsolete work and
terminate its process where possible. Late responses must still match the
request identity and current document version before publication. Closing and
reopening the same URI also invalidates pending work. Diagnostics clear immediately
on an edit or close; a cancelled response cannot restore them. Timers, abort listeners,
process streams, event subscriptions, and processes are disposed on shutdown.
Responses larger than 16 MiB are rejected.

## Launch the Extension Development Host

1. Open **this `datalang-vscode` folder** in desktop VS Code, so its generated
   `.vscode/launch.json` and `.vscode/tasks.json` are active.
2. Run `npm install` in this folder, then `npm run compile` and `npm run lint`.
   In PowerShell environments that block `npm.ps1`, use `npm.cmd` in place of `npm`.
3. In **Run and Debug**, select **Run Extension** and press **F5**. The existing
   default build task runs `npm run watch` with the TypeScript watch problem matcher,
   then opens a new **Extension Development Host** window.
4. In that new window, open the DataLang repository and any `.dl` file, or create
   `example.dl` using the sample below. The language mode should read **DataLang**.
   For an untitled file, choose **DataLang** from the language-mode picker.
5. Edit TypeScript in the original window; the watch task rebuilds `out/`.
   Restart debugging to load runtime changes. Reload the development window or
   restart debugging after changing the manifest or grammar.

If launching reports **Code is currently being updated**, save your work and use
VS Code's **Restart to Update** action. If necessary, close all VS Code windows,
allow the update to finish, then reopen this folder and press **F5** again.

```datalang
# Case-insensitive keywords; all statements end in semicolons.
LOAD "sales.csv" AS sales;
FILTER sales WHERE Revenue >= 1000 AND NOT Region == "South";
AGGREGATE SUM(Revenue) FROM sales GROUP BY Region;
SORT sum_Revenue DESC FROM sales;
VISUALIZE BAR OF sum_Revenue FROM sales;
```

Use **Developer: Inspect Editor Tokens and Scopes** in the development window to
inspect `source.datalang` scopes. **Toggle Line Comment** should insert `#`.
To check Restricted Mode, use **Workspaces: Manage Workspace Trust** in the
development window; highlighting should remain available.

## Build tooling

The generated TypeScript compiler, ESLint, npm scripts, and VS Code launch/watch
tasks are retained. `npm run compile` writes `out/`; `npm run watch` rebuilds on
changes; `npm run lint` checks TypeScript. `npm run test:unit` runs the bridge,
Unicode position conversions, DiagnosticCollection lifecycle, and
debounce/cancellation tests in Node without opening VS Code. From the repository
root, `python -m pytest tests/test_editor_bridge.py tests/test_editor_diagnostic_spans.py -q` checks real Python
stdin/stdout exchanges. `npm test` runs the generated VS Code
extension test runner, whose first run may download VS Code and open a test window.
The host tests also exercise real Python diagnostics; they use `python` on PATH.
Set the `DATALANG_TEST_PYTHON` environment variable to use another interpreter.
