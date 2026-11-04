import * as assert from 'assert';

import * as vscode from 'vscode';

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
});
