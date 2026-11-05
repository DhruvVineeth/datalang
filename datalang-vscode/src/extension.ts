import * as path from 'node:path';
import * as vscode from 'vscode';
import { AnalysisController, AnalysisSettings, DocumentSnapshot } from './analysisController';
import { BackendClient } from './backendClient';

let controller: AnalysisController | undefined;

export function activate(context: vscode.ExtensionContext): void {
	let disposed = false;
	const output = vscode.window.createOutputChannel('DataLang');
	const diagnostics = vscode.languages.createDiagnosticCollection('datalang');
	const reportedErrors = new Set<string>();
	const client = new BackendClient(() => vscode.workspace.isTrusted, text => {
		if (!disposed) { output.append(text); }
	});
	const currentDocument = (snapshot: DocumentSnapshot) => vscode.workspace.textDocuments.find(
		document => document.uri.toString() === snapshot.uri && document.version === snapshot.version
			&& !document.isClosed && document.languageId === 'datalang',
	);
	controller = new AnalysisController(client, snapshot => !!currentDocument(snapshot), (snapshot, result) => {
		const document = currentDocument(snapshot);
		if (!document) { return; }
		diagnostics.set(document.uri, result.analysis.diagnostics.map(error => {
			const line = Math.min(Math.max((error.line ?? 1) - 1, 0), document.lineCount - 1);
			const text = document.lineAt(line).text;
			// Python uses code points; VS Code uses UTF-16 code units.
			const column = [...text].slice(0, error.column ?? 0).join('').length;
			const width = text.codePointAt(column) === undefined ? 0 : String.fromCodePoint(text.codePointAt(column)!).length;
			const diagnostic = new vscode.Diagnostic(
				new vscode.Range(line, column, line, column + width), error.message, vscode.DiagnosticSeverity.Error,
			);
			diagnostic.source = 'DataLang';
			diagnostic.code = error.stage;
			return diagnostic;
		}));
	}, (snapshot, error) => {
		output.appendLine(`[${snapshot.uri} version ${snapshot.version}] ${error.message}`);
		if (!reportedErrors.has(error.message)) {
			reportedErrors.add(error.message);
			void vscode.window.showErrorMessage(`DataLang: ${error.message}`);
		}
	});
	const analysis = controller;
	const schedule = (document: vscode.TextDocument) => {
		if (document.languageId !== 'datalang' || document.isClosed
			|| !['file', 'untitled'].includes(document.uri.scheme)) {
			analysis.cancel(document.uri.toString());
			diagnostics.delete(document.uri);
			return;
		}
		// Clear diagnostics from the previous version as soon as text changes.
		diagnostics.delete(document.uri);
		if (!vscode.workspace.isTrusted) {
			analysis.cancel(document.uri.toString());
			return;
		}
		const config = vscode.workspace.getConfiguration('datalang', document.uri);
		const settings: AnalysisSettings = {
			pythonExecutable: config.get('pythonExecutable', 'python'),
			backendPath: config.get('backendPath', ''),
			analysisDebounceMs: config.get('analysisDebounceMs', 300),
			analysisTimeoutMs: config.get('analysisTimeoutMs', 10000),
		};
		const folder = vscode.workspace.getWorkspaceFolder(document.uri) ?? vscode.workspace.workspaceFolders?.[0];
		const documentPath = document.uri.scheme === 'file' ? document.uri.fsPath
			: path.resolve(folder?.uri.fsPath ?? settings.backendPath, 'Untitled.dl');
		analysis.schedule({
			uri: document.uri.toString(), path: documentPath,
			version: document.version, text: document.getText(),
		}, settings);
	};
	const scheduleAll = () => vscode.workspace.textDocuments.forEach(schedule);
	context.subscriptions.push(
		{ dispose: () => { disposed = true; analysis.dispose(); } }, diagnostics, output,
		vscode.workspace.onDidOpenTextDocument(schedule),
		vscode.workspace.onDidChangeTextDocument(event => schedule(event.document)),
		vscode.workspace.onDidCloseTextDocument(document => {
			analysis.cancel(document.uri.toString());
			diagnostics.delete(document.uri);
		}),
		vscode.workspace.onDidGrantWorkspaceTrust(scheduleAll),
		vscode.workspace.onDidChangeConfiguration(event => {
			if (event.affectsConfiguration('datalang')) { reportedErrors.clear(); scheduleAll(); }
		}),
	);
	scheduleAll();
}

export function deactivate(): void {
	controller?.dispose();
	controller = undefined;
}
