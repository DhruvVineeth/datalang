import * as vscode from 'vscode';
import { BackendDiagnostic } from './backendProtocol';
import { diagnosticRange } from './positions';

export function toDiagnostic(document: vscode.TextDocument, error: BackendDiagnostic): vscode.Diagnostic {
	const { start, end } = diagnosticRange(document, error);
	const diagnostic = new vscode.Diagnostic(
		new vscode.Range(start.line, start.character, end.line, end.character),
		error.message, vscode.DiagnosticSeverity.Error,
	);
	diagnostic.source = 'DataLang';
	diagnostic.code = error.stage;
	return diagnostic;
}
