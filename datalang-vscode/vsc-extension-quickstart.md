# DataLang extension development

Open this folder in desktop VS Code, install dependencies with `npm install`, and
press **F5** with **Run Extension** selected. The generated default build task runs
`npm run watch`; the new **Extension Development Host** loads the extension.
Open a `.dl` file there and check that the language mode is **DataLang**.

In PowerShell environments that block `npm.ps1`, use `npm.cmd` instead of `npm`.

- `package.json`: language ID, `.dl` association, grammar, settings, and trust policy.
- `language-configuration.json`: comments, parentheses, and double-quote pairs.
- `syntaxes/datalang.tmLanguage.json`: highlighting based on the Python lexer/parser.
- `src/extension.ts`: runtime entry point; backend startup is not implemented yet.
- `.vscode/launch.json` and `.vscode/tasks.json`: generated F5 and TypeScript watch setup.

Run `npm run compile` and `npm run lint` to check changes. Use
**Developer: Inspect Editor Tokens and Scopes** in the development window to inspect
highlighting. Restart debugging after runtime changes; reload the development
window or restart debugging after manifest or grammar changes.

See [README.md](README.md) for settings, the workspace-trust policy, and a sample.
