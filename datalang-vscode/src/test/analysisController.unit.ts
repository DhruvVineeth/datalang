import * as assert from 'node:assert/strict';
import { test } from 'node:test';
import { AnalysisController, AnalysisSettings, DocumentSnapshot } from '../analysisController';
import { BackendSettings } from '../backendClient';
import { AnalysisPayloadResult, AnalysisRequest } from '../backendProtocol';

const settings: AnalysisSettings = {
	pythonExecutable: 'python', backendPath: '/backend', analysisDebounceMs: 10, analysisTimeoutMs: 1000,
};
const document: DocumentSnapshot = { uri: 'file:///example.dl', path: '/example.dl', version: 1, text: 'unsaved text' };
const payload = (version: number): AnalysisPayloadResult => ({
	analysis: { document_path: document.path, document_version: version, diagnostics: [], datasets: [], statements: [] }, cursor: null,
});
const wait = () => new Promise(resolve => setTimeout(resolve, 25));

class Transport {
	calls: { request: AnalysisRequest; signal: AbortSignal; resolve(value: AnalysisPayloadResult): void; reject(error: Error): void }[] = [];
	disposed = false;
	request(request: AnalysisRequest, _settings: BackendSettings, signal: AbortSignal): Promise<AnalysisPayloadResult> {
		return new Promise((resolve, reject) => this.calls.push({ request, signal, resolve, reject }));
	}
	dispose(): void { this.disposed = true; }
}

function harness() {
	const transport = new Transport();
	const published: number[] = [];
	const errors: string[] = [];
	let version = 1;
	const controller = new AnalysisController(transport, snapshot => snapshot.version === version,
		snapshot => published.push(snapshot.version), (_snapshot, error) => errors.push(error.message));
	return { transport, controller, published, errors, setVersion: (value: number) => { version = value; } };
}

test('debounce sends only the newest unsaved text', async () => {
	const run = harness();
	run.controller.schedule(document, settings);
	run.controller.schedule({ ...document, version: 2, text: 'new unsaved text' }, settings);
	run.setVersion(2);
	assert.equal(run.transport.calls.length, 0);
	await wait();
	assert.equal(run.transport.calls.length, 1);
	assert.equal(run.transport.calls[0].request.text, 'new unsaved text');
	assert.equal(run.transport.calls[0].request.document_version, 2);
	run.transport.calls[0].resolve(payload(2));
	await wait();
	assert.deepEqual(run.published, [2]);
	run.controller.dispose();
});

test('edits cancel obsolete work and late responses cannot publish', async () => {
	const run = harness();
	run.controller.schedule(document, settings);
	await wait();
	run.setVersion(2);
	run.controller.schedule({ ...document, version: 2 }, settings);
	assert.equal(run.transport.calls[0].signal.aborted, true);
	run.transport.calls[0].resolve(payload(1)); // Simulate cancellation losing a race.
	await wait();
	assert.deepEqual(run.published, []);
	run.transport.calls[1].resolve(payload(2));
	await wait();
	assert.deepEqual(run.published, [2]);
	run.controller.dispose();
});

test('checks current document version again after response arrival', async () => {
	const run = harness();
	run.controller.schedule(document, settings);
	await wait();
	run.setVersion(2); // Even without another scheduled request, this response is stale.
	run.transport.calls[0].resolve(payload(1));
	await wait();
	assert.deepEqual(run.published, []);
	run.controller.dispose();
});

test('close and reopen with the same URI/version still rejects the old request', async () => {
	const run = harness();
	run.controller.schedule(document, settings);
	await wait();
	run.controller.cancel(document.uri);
	run.controller.schedule(document, settings);
	run.transport.calls[0].resolve(payload(1));
	await wait();
	assert.deepEqual(run.published, []);
	run.transport.calls[1].resolve(payload(1));
	await wait();
	assert.deepEqual(run.published, [1]);
	run.controller.dispose();
});

test('document timers are isolated and cancellation prevents pending starts', async () => {
	const run = harness();
	run.controller.schedule(document, settings);
	run.controller.schedule({ ...document, uri: 'untitled:other' }, settings);
	run.controller.cancel(document.uri);
	await wait();
	assert.equal(run.transport.calls.length, 1);
	assert.equal(run.transport.calls[0].request.document_uri, 'untitled:other');
	run.controller.dispose();
});

test('dispose clears timers, aborts requests, and suppresses late errors', async () => {
	const run = harness();
	run.controller.schedule(document, settings);
	await wait();
	run.controller.schedule({ ...document, uri: 'untitled:pending' }, settings);
	run.controller.dispose();
	assert.equal(run.transport.disposed, true);
	assert.equal(run.transport.calls[0].signal.aborted, true);
	run.transport.calls[0].reject(new Error('late failure'));
	run.controller.schedule(document, settings);
	await wait();
	assert.equal(run.transport.calls.length, 1);
	assert.deepEqual(run.errors, []);
});

test('startup failures are reported only for a still-current document', async () => {
	const run = harness();
	run.controller.schedule(document, settings);
	await wait();
	run.transport.calls[0].reject(new Error('Python not found'));
	await wait();
	assert.deepEqual(run.errors, ['Python not found']);
	run.controller.dispose();
});

test('unconfigured backend cancels work without starting a process', async () => {
	const run = harness();
	run.controller.schedule(document, settings);
	run.controller.schedule(document, { ...settings, backendPath: '' });
	await wait();
	assert.equal(run.transport.calls.length, 0);
	run.controller.dispose();
});
