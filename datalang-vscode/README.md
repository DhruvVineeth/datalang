# DataLang for VS Code

Registers the language ID `datalang` for `.dl` files, with syntax highlighting,
`#` line-comment toggling, parenthesis matching, and automatic closing and
surrounding of parentheses and double quotes.

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
  "datalang.analysisDebounceMs": 300
}
```

| Setting | Default | Meaning |
| --- | --- | --- |
| `datalang.pythonExecutable` | `"python"` | Executable on PATH or an absolute interpreter path, for example `C:/path/to/.venv/Scripts/python.exe`. Do not include arguments. |
| `datalang.backendPath` | `""` | Absolute DataLang repository root containing `src/lexer/lexer.py` and `src/parser/parser.py`. Empty leaves the backend unconfigured. |
| `datalang.analysisDebounceMs` | `300` | Milliseconds to wait after the last edit before analysis; integer from `0` to `60000`. `0` requests immediate analysis. |

Executable and backend paths are machine-specific settings that can be overridden
per workspace or folder. The debounce setting can also vary per folder.

This scaffold declares the backend settings and trust policy; it does not yet
launch a Python backend or provide live diagnostics. Python and the DataLang
dependencies are not needed for syntax highlighting.

## Workspace trust

Restricted Mode supports syntax highlighting and editor configuration. Python
backend execution requires a trusted workspace, since the interpreter and backend
location select code to execute. Workspace overrides of `datalang.pythonExecutable`
and `datalang.backendPath` are restricted until trust is granted.

When adding the backend client, check `vscode.workspace.isTrusted` immediately
before spawning a process, including when using user-level settings. Restricted
settings alone do not block process execution. If the client should start after
trust is granted, subscribe to `vscode.workspace.onDidGrantWorkspaceTrust`.
See the [VS Code Workspace Trust guide](https://code.visualstudio.com/api/extension-guides/workspace-trust).

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
changes; `npm run lint` checks TypeScript. `npm test` runs the generated VS Code
extension test runner, whose first run may download VS Code and open a test window.
