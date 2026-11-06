import type { TextDocument } from 'vscode';
import type { BackendDiagnostic } from './backendProtocol';

export interface CompilerPosition { line: number; column: number }
export interface EditorPosition { line: number; character: number }
type DocumentLines = Pick<TextDocument, 'lineCount' | 'lineAt'>;

/** Compiler lines are one-based and columns count Unicode code points.
 * VS Code lines are zero-based and characters count UTF-16 code units.
 * Out-of-bounds positions are clamped to the document. Neither direction
 * splits an astral character; an editor position inside a surrogate pair
 * maps to its beginning. Combining marks each count as one code point.
 */
export function compilerToEditorPosition(document: DocumentLines, position: CompilerPosition): EditorPosition {
	const line = Math.min(Math.max(position.line - 1, 0), document.lineCount - 1);
	const text = document.lineAt(line).text;
	let character = 0;
	let column = 0;
	for (const point of text) {
		if (column >= position.column) { break; }
		character += point.length;
		column++;
	}
	return { line, character };
}

export function editorToCompilerPosition(document: DocumentLines, position: EditorPosition): CompilerPosition {
	const line = Math.min(Math.max(position.line, 0), document.lineCount - 1);
	let character = 0;
	let column = 0;
	for (const point of document.lineAt(line).text) {
		if (character + point.length > position.character) { break; }
		character += point.length;
		column++;
	}
	return { line: line + 1, column };
}

/** Use exclusive backend ends; legacy diagnostics select one code point.
 * An unknown column selects the whole line. EOF stays an empty range.
 */
export function diagnosticRange(document: DocumentLines, diagnostic: BackendDiagnostic): {
	start: EditorPosition; end: EditorPosition;
} {
	const line = diagnostic.line ?? 1;
	const column = diagnostic.column ?? 0;
	const start = compilerToEditorPosition(document, { line, column });
	let end: EditorPosition;
	if (typeof diagnostic.end_line === 'number' && typeof diagnostic.end_column === 'number') {
		end = compilerToEditorPosition(document, { line: diagnostic.end_line, column: diagnostic.end_column });
	} else if (diagnostic.column === null) {
		end = { line: start.line, character: document.lineAt(start.line).text.length };
	} else {
		end = compilerToEditorPosition(document, { line, column: column + 1 });
	}
	if (end.line < start.line || (end.line === start.line && end.character < start.character)) { end = start; }
	return { start, end };
}
