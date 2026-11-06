export interface AnalysisRequest {
	protocol_version: 1;
	request_id: string;
	method: 'analyze' | 'cursor';
	document_uri: string;
	document_path: string;
	document_version: number;
	text: string;
	position?: { line: number; column: number };
}

export interface BackendDiagnostic {
	stage: 'lexical' | 'syntax' | 'semantic';
	message: string;
	line: number | null;
	column: number | null;
	severity: 'error';
	/** Exclusive end in compiler coordinates. Optional for older backends. */
	end_line?: number | null;
	end_column?: number | null;
}

export interface AnalysisPayload {
	document_path: string;
	document_version: number;
	diagnostics: BackendDiagnostic[];
	datasets: unknown[];
	statements: unknown[];
}

export interface AnalysisPayloadResult {
	analysis: AnalysisPayload;
	cursor: unknown;
}

export interface AnalysisResponse {
	protocol_version: 1;
	request_id: string;
	document_uri: string;
	document_version: number;
	ok: boolean;
	result?: AnalysisPayloadResult;
	error?: { code: string; message: string };
}

function object(value: unknown): value is Record<string, unknown> {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function diagnostic(value: unknown): value is BackendDiagnostic {
	if (!object(value)) { return false; }
	const hasEnd = (value.end_line ?? null) !== null || (value.end_column ?? null) !== null;
	return (!hasEnd || (Number.isInteger(value.end_line) && Number.isInteger(value.end_column)
		&& (value.end_line as number) >= 1 && (value.end_column as number) >= 0
		&& Number.isInteger(value.line) && Number.isInteger(value.column)
		&& ((value.end_line as number) > (value.line as number)
			|| (value.end_line === value.line && (value.end_column as number) >= (value.column as number)))))
		&& ['lexical', 'syntax', 'semantic'].includes(value.stage as string)
		&& typeof value.message === 'string' && value.severity === 'error'
		&& (value.line === null || (Number.isInteger(value.line) && (value.line as number) >= 1))
		&& (value.column === null || (Number.isInteger(value.column) && (value.column as number) >= 0));
}

/** Validate the envelope and the fields used by the diagnostic publisher. */
export function parseResponse(text: string, request: AnalysisRequest): AnalysisResponse {
	const value: unknown = JSON.parse(text);
	if (!object(value) || value.protocol_version !== 1
		|| value.request_id !== request.request_id || value.document_uri !== request.document_uri
		|| value.document_version !== request.document_version || typeof value.ok !== 'boolean') {
		throw new Error('Response identity or protocol version does not match the request.');
	}
	if (!value.ok) {
		if (!object(value.error) || typeof value.error.code !== 'string'
			|| typeof value.error.message !== 'string') {
			throw new Error('Invalid backend error response.');
		}
	} else {
		const result = value.result;
		const analysis = object(result) ? result.analysis : undefined;
		if (!object(analysis) || typeof analysis.document_path !== 'string'
			|| analysis.document_version !== request.document_version
			|| !Array.isArray(analysis.diagnostics) || !analysis.diagnostics.every(diagnostic)
			|| !Array.isArray(analysis.datasets) || !Array.isArray(analysis.statements)) {
			throw new Error('Invalid analysis result.');
		}
	}
	return value as unknown as AnalysisResponse;
}
