import * as assert from 'node:assert/strict';
import { test } from 'node:test';
import type { TextDocument } from 'vscode';
import { BackendDiagnostic } from '../backendProtocol';
import { compilerToEditorPosition, diagnosticRange, editorToCompilerPosition } from '../positions';

function document(text: string): TextDocument {
	const lines = text.split(/\r\n|\n/);
	return { lineCount: lines.length, lineAt: (line: number) => ({ text: lines[line] }) } as TextDocument;
}

test('compiler and editor coordinates round trip at every Unicode code point boundary', () => {
	for (const eol of ['\n', '\r\n']) {
		const lines = ['', 'ascii', '\té😀e\u0301𐐀中\ud800', ''];
		const doc = document(lines.join(eol));
		for (let line = 0; line < lines.length; line++) {
			const points = [...lines[line]];
			for (let column = 0; column <= points.length; column++) {
				const compiler = { line: line + 1, column };
				const editor = { line, character: points.slice(0, column).join('').length };
				assert.deepEqual(compilerToEditorPosition(doc, compiler), editor);
				assert.deepEqual(editorToCompilerPosition(doc, editor), compiler);
			}
		}
	}
});

test('conversions clamp bounds and positions inside surrogate pairs snap to the start', () => {
	const doc = document('a😀z\n');
	assert.deepEqual(editorToCompilerPosition(doc, { line: 0, character: 2 }), { line: 1, column: 1 });
	assert.deepEqual(editorToCompilerPosition(doc, { line: -5, character: -5 }), { line: 1, column: 0 });
	assert.deepEqual(compilerToEditorPosition(doc, { line: -5, column: -5 }), { line: 0, character: 0 });
	assert.deepEqual(compilerToEditorPosition(doc, { line: 1, column: 999 }), { line: 0, character: 4 });
	assert.deepEqual(compilerToEditorPosition(doc, { line: 99, column: 999 }), { line: 1, character: 0 });
	assert.deepEqual(editorToCompilerPosition(doc, { line: 99, character: 999 }), { line: 2, column: 0 });
});

const diagnostic: BackendDiagnostic = { stage: 'semantic', message: 'bad column', severity: 'error', line: 1, column: 2 };

test('diagnostic ranges convert both exclusive ends, including multiline Unicode literals', () => {
	const doc = document('😀 unknown\r\n"é😀\nvalue";');
	assert.deepEqual(diagnosticRange(doc, { ...diagnostic, end_line: 1, end_column: 9 }), {
		start: { line: 0, character: 3 }, end: { line: 0, character: 10 },
	});
	assert.deepEqual(diagnosticRange(doc, { ...diagnostic, line: 2, column: 0, end_line: 3, end_column: 6 }), {
		start: { line: 1, character: 0 }, end: { line: 2, character: 6 },
	});
});

test('legacy, unknown, empty, out-of-bounds and EOF ranges have safe fallbacks', () => {
	const doc = document('a😀z\n');
	assert.deepEqual(diagnosticRange(doc, { ...diagnostic, column: 1 }), {
		start: { line: 0, character: 1 }, end: { line: 0, character: 3 },
	});
	assert.deepEqual(diagnosticRange(doc, { ...diagnostic, column: null }), {
		start: { line: 0, character: 0 }, end: { line: 0, character: 4 },
	});
	for (const error of [{ ...diagnostic, line: 2, column: 0 }, { ...diagnostic, line: 99, column: 99 }]) {
		assert.deepEqual(diagnosticRange(doc, error), { start: { line: 1, character: 0 }, end: { line: 1, character: 0 } });
	}
	assert.deepEqual(diagnosticRange(document(''), { ...diagnostic, line: null, column: null }), {
		start: { line: 0, character: 0 }, end: { line: 0, character: 0 },
	});
	assert.deepEqual(diagnosticRange(doc, { ...diagnostic, column: 1, end_line: 1, end_column: 1 }), {
		start: { line: 0, character: 1 }, end: { line: 0, character: 1 },
	});
});
