import * as assert from 'assert';

import * as vscode from 'vscode';
import * as path from 'node:path';
import * as fs from 'node:fs/promises';
import * as os from 'node:os';

suite('DataLang extension', () => {
	test('loads and activates in the Extension Development Host', async () => {
		const extension = vscode.extensions.all.find(
			candidate => candidate.packageJSON.name === 'datalang-vscode'
		);
		assert.ok(extension, 'DataLang must be loaded by the extension host');
		await extension.activate();
		assert.strictEqual(extension.isActive, true);
	});

	test('registers the DataLang language', async () => {
		const languages = await vscode.languages.getLanguages();
		assert.ok(languages.includes('datalang'));
	});

	test('publishes real backend ranges for unknown/removed columns, type errors, missing files and syntax', async function () {
		this.timeout(30000);
		const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'datalang-diagnostics-'));
		const backendPath = path.resolve(__dirname, '../../..');
		const config = vscode.workspace.getConfiguration('datalang');
		const previous = ['backendPath', 'pythonExecutable', 'analysisDebounceMs'].map(key => ({
			key, value: config.inspect(key)?.globalValue,
		}));
		const documents: vscode.TextDocument[] = [];
		const waitForDiagnostics = (uri: vscode.Uri, predicate: (diagnostics: readonly vscode.Diagnostic[]) => boolean) =>
			new Promise<readonly vscode.Diagnostic[]>((resolve, reject) => {
				const timer = setTimeout(() => { subscription.dispose(); reject(new Error(`No expected diagnostics for ${uri}`)); }, 10000);
				const check = () => {
					const diagnostics = vscode.languages.getDiagnostics(uri);
					if (predicate(diagnostics)) { clearTimeout(timer); subscription.dispose(); resolve(diagnostics); }
				};
				const subscription = vscode.languages.onDidChangeDiagnostics(check);
				check();
			});
		try {
			await config.update('backendPath', backendPath, vscode.ConfigurationTarget.Global);
			await config.update('pythonExecutable', process.env.DATALANG_TEST_PYTHON ?? 'python', vscode.ConfigurationTarget.Global);
			await config.update('analysisDebounceMs', 20, vscode.ConfigurationTarget.Global);
			await fs.writeFile(path.join(directory, 'data.csv'), 'label,amount\nA,2.5\n', 'utf8');
			const cases = [
				['SELECT missing FROM sales;', 'missing', 'semantic'],
				['SELECT label FROM sales; SELECT amount FROM sales;', 'amount', 'semantic'],
				['FILTER sales WHERE amount > "two";', '"two"', 'semantic'],
				['LOAD "missing.csv" AS absent;', '"missing.csv"', 'semantic'],
				['SELECT label WRONG sales;', 'WRONG', 'syntax'],
			];
			for (const [index, [fragment, target, stage]] of cases.entries()) {
				const text = 'LOAD "data.csv" AS sales; FILTER sales WHERE label == "😀"; ' + fragment;
				const uri = vscode.Uri.file(path.join(directory, `case-${index}.dl`));
				await fs.writeFile(uri.fsPath, text, 'utf8');
				const document = await vscode.workspace.openTextDocument(uri);
				documents.push(document);
				const diagnostics = await waitForDiagnostics(uri, errors => errors.length === 1);
				assert.strictEqual(document.getText(diagnostics[0].range), target);
				assert.strictEqual(diagnostics[0].code, stage);
				assert.strictEqual(diagnostics[0].source, 'DataLang');
				assert.strictEqual(diagnostics[0].severity, vscode.DiagnosticSeverity.Error);
			}
			// A valid unsaved edit clears diagnostics and is analyzed from the buffer.
			const document = documents[0];
			const changes = new vscode.WorkspaceEdit();
			changes.replace(document.uri, new vscode.Range(document.positionAt(0), document.positionAt(document.getText().length)),
				'LOAD "data.csv" AS sales; SELECT amount FROM sales;');
			await vscode.workspace.applyEdit(changes);
			await waitForDiagnostics(document.uri, errors => errors.length === 0);
			await document.save();
			// Untitled buffers close immediately; file models may be cached after a tab closes.
			const closed = await vscode.workspace.openTextDocument({ language: 'datalang', content: 'SELECT missing FROM missing;' });
			await waitForDiagnostics(closed.uri, errors => errors.length === 1);
			await vscode.window.showTextDocument(closed);
			const didClose = new Promise<void>((resolve, reject) => {
				const timer = setTimeout(() => { subscription.dispose(); reject(new Error('Untitled document did not close')); }, 10000);
				const subscription = vscode.workspace.onDidCloseTextDocument(doc => {
					if (doc.uri.toString() === closed.uri.toString()) { clearTimeout(timer); subscription.dispose(); resolve(); }
				});
			});
			await vscode.commands.executeCommand('workbench.action.revertAndCloseActiveEditor');
			await didClose;
			assert.deepStrictEqual(vscode.languages.getDiagnostics(closed.uri), []);
		} finally {
			await vscode.commands.executeCommand('workbench.action.closeAllEditors');
			for (const { key, value } of previous) { await config.update(key, value, vscode.ConfigurationTarget.Global); }
			for (const file of await fs.readdir(directory)) { await fs.unlink(path.join(directory, file)); }
			await fs.rmdir(directory);
		}
	});
});
