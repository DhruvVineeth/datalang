import { randomUUID } from 'node:crypto';
import { BackendClient, BackendSettings, RequestCancelledError } from './backendClient';
import { AnalysisPayloadResult } from './backendProtocol';

export interface DocumentSnapshot {
	uri: string;
	path: string;
	version: number;
	text: string;
}

export interface AnalysisSettings extends BackendSettings {
	analysisDebounceMs: number;
}

type Transport = Pick<BackendClient, 'request' | 'dispose'>;
interface Pending {
	abort: AbortController;
	timer?: NodeJS.Timeout;
}

/** Own debounce timers and in-flight requests independently for each URI. */
export class AnalysisController {
	private readonly pending = new Map<string, Pending>();
	private disposed = false;

	constructor(
		private readonly client: Transport,
		private readonly isCurrent: (document: DocumentSnapshot) => boolean,
		private readonly publish: (document: DocumentSnapshot, result: AnalysisPayloadResult) => void,
		private readonly reportError: (document: DocumentSnapshot, error: Error) => void,
	) {}

	schedule(document: DocumentSnapshot, settings: AnalysisSettings): void {
		this.cancel(document.uri);
		if (this.disposed || !settings.backendPath.trim()) { return; }
		const pending: Pending = { abort: new AbortController() };
		this.pending.set(document.uri, pending);
		pending.timer = setTimeout(async () => {
			pending.timer = undefined;
			const current = () => !this.disposed && !pending.abort.signal.aborted
				&& this.pending.get(document.uri) === pending && this.isCurrent(document);
			try {
				if (!current()) { return; }
				const result = await this.client.request({
					protocol_version: 1,
					request_id: randomUUID(),
					method: 'analyze',
					document_uri: document.uri,
					document_path: document.path,
					document_version: document.version,
					text: document.text,
				}, settings, pending.abort.signal);
				// Cancellation is best effort. Check version/identity even if a process
				// completed before termination or the document was closed and reopened.
				if (current()) { this.publish(document, result); }
			} catch (error) {
				if (current() && !(error instanceof RequestCancelledError)) {
					this.reportError(document, error as Error);
				}
			} finally {
				if (this.pending.get(document.uri) === pending) { this.pending.delete(document.uri); }
			}
		}, settings.analysisDebounceMs);
	}

	cancel(uri: string): void {
		const pending = this.pending.get(uri);
		if (!pending) { return; }
		this.pending.delete(uri);
		clearTimeout(pending.timer);
		pending.abort.abort();
	}

	dispose(): void {
		if (this.disposed) { return; }
		this.disposed = true;
		for (const uri of this.pending.keys()) { this.cancel(uri); }
		this.client.dispose();
	}
}
