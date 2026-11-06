import * as assert from 'node:assert/strict';
import Module = require('node:module');
import { mock, test } from 'node:test';
import { BackendClient, BackendSettings } from '../backendClient';
import { AnalysisPayloadResult, AnalysisRequest, BackendDiagnostic } from '../backendProtocol';

test('DiagnosticCollection follows open, debounced edits, close, reopen and disposal', async () => {
	mock.timers.enable({ apis: ['setTimeout'] });
	class Range {
		start: { line: number; character: number };
		end: { line: number; character: number };
		constructor(line: number, character: number, endLine: number, endCharacter: number) {
			this.start = { line, character }; this.end = { line: endLine, character: endCharacter };
		}
	}
	class Diagnostic {
		source?: string;
		code?: string;
		constructor(public range: Range, public message: string, public severity: number) {}
	}
	const entries = new Map<string, Diagnostic[]>();
	const collection = {
		set: (uri: { toString(): string }, errors: Diagnostic[]) => { entries.set(uri.toString(), errors); },
		delete: (uri: { toString(): string }) => { entries.delete(uri.toString()); },
		dispose: () => entries.clear(),
	};
	type EventHandler = (event: any) => void;
	const events = new Map<string, EventHandler>();
	const listen = (name: string) => (handler: EventHandler) => {
		events.set(name, handler);
		return { dispose: () => events.delete(name) };
	};
	const uri = { toString: () => 'file:///example.dl', scheme: 'file', fsPath: '/example.dl' };
	const document = {
		uri, version: 1, languageId: 'datalang', isClosed: false, lineCount: 1,
		getText: () => '😀 unknown', lineAt: () => ({ text: '😀 unknown' }),
	};
	const workspace = {
		isTrusted: true, textDocuments: [document], workspaceFolders: [],
		getWorkspaceFolder: () => undefined,
		getConfiguration: () => ({ get: (name: string, fallback: unknown) =>
			({ backendPath: '/backend', analysisDebounceMs: 30 } as Record<string, unknown>)[name] ?? fallback }),
		onDidOpenTextDocument: listen('open'), onDidChangeTextDocument: listen('change'),
		onDidCloseTextDocument: listen('close'), onDidGrantWorkspaceTrust: listen('trust'),
		onDidChangeConfiguration: listen('config'),
	};
	const errors: string[] = [];
	const api = {
		workspace, Range, Diagnostic, DiagnosticSeverity: { Error: 0 },
		languages: { createDiagnosticCollection: (name: string) => { assert.equal(name, 'datalang'); return collection; } },
		window: {
			createOutputChannel: () => ({ append() {}, appendLine() {}, dispose() {} }),
			showErrorMessage: (message: string) => { errors.push(message); },
		},
	};
	const loader = Module as unknown as { _load(id: string, ...args: unknown[]): unknown };
	const originalLoad = loader._load;
	const loadMock = mock.method(loader, '_load', (id: string, ...args: unknown[]) =>
		id === 'vscode' ? api : originalLoad.call(Module, id, ...args));
	const extension: typeof import('../extension') = require('../extension');
	loadMock.mock.restore();
	const calls: { request: AnalysisRequest; signal: AbortSignal; resolve(result: AnalysisPayloadResult): void }[] = [];
	const requestMock = mock.method(BackendClient.prototype, 'request',
		(request: AnalysisRequest, _settings: BackendSettings, signal: AbortSignal) =>
			new Promise<AnalysisPayloadResult>(resolve => calls.push({ request, signal, resolve })));
	const subscriptions: { dispose(): void }[] = [];
	const diagnostic: BackendDiagnostic = {
		stage: 'semantic', message: 'Unknown column', severity: 'error', line: 1, column: 2, end_line: 1, end_column: 9,
	};
	const finish = async (index: number, diagnostics = [diagnostic]) => {
		calls[index].resolve({ analysis: {
			document_path: '/example.dl', document_version: calls[index].request.document_version,
			diagnostics, datasets: [], statements: [],
		}, cursor: null });
		await Promise.resolve();
	};
	const edit = () => {
		document.version++;
		events.get('change')!({ document, contentChanges: [{ text: 'edit' }] });
	};
	try {
		extension.activate({ subscriptions } as unknown as import('vscode').ExtensionContext);
		// Documents already open at activation are analyzed immediately.
		mock.timers.tick(0);
		assert.equal(calls.length, 1);
		await finish(0);
		const published = entries.get(uri.toString())!;
		assert.equal(published.length, 1);
		assert.equal(published[0].source, 'DataLang');
		assert.equal(published[0].code, 'semantic');
		assert.equal(published[0].severity, 0);
		assert.deepEqual(published[0].range.start, { line: 0, character: 3 });
		assert.deepEqual(published[0].range.end, { line: 0, character: 10 });
		// Dirty-state-only events leave current diagnostics intact.
		events.get('change')!({ document, contentChanges: [] });
		assert.equal(entries.size, 1);
		edit(); edit();
		assert.equal(entries.size, 0);
		mock.timers.tick(29);
		assert.equal(calls.length, 1);
		mock.timers.tick(1);
		assert.equal(calls.length, 2);
		assert.equal(calls[1].request.document_version, 3);
		edit(); // Clear and supersede an in-flight request.
		await finish(1);
		assert.equal(entries.size, 0);
		mock.timers.tick(30);
		await finish(2, []);
		assert.deepEqual(entries.get(uri.toString()), []);
		edit();
		mock.timers.tick(30);
		document.isClosed = true; workspace.textDocuments = [];
		events.get('close')!(document);
		assert.equal(entries.size, 0);
		assert.equal(calls[3].signal.aborted, true);
		// Reopening the same URI/version must not admit the previous response.
		document.isClosed = false; workspace.textDocuments = [document];
		events.get('open')!(document);
		mock.timers.tick(0);
		await finish(3);
		assert.equal(entries.size, 0);
		await finish(4);
		assert.equal(entries.size, 1);
		edit(); // Closing during debounce also prevents a process from starting.
		document.isClosed = true; workspace.textDocuments = [];
		events.get('close')!(document);
		mock.timers.tick(30);
		assert.equal(calls.length, 5);
		assert.equal(entries.size, 0);
		document.isClosed = false; workspace.textDocuments = [document];
		events.get('open')!(document);
		mock.timers.tick(0);
		for (const disposable of subscriptions) { disposable.dispose(); }
		await finish(5); // Disposing the extension also suppresses late publication.
		assert.equal(entries.size, 0);
		assert.deepEqual(errors, []);
	} finally {
		for (const disposable of subscriptions) { disposable.dispose(); }
		extension.deactivate();
		requestMock.mock.restore();
		mock.timers.reset();
	}
});
