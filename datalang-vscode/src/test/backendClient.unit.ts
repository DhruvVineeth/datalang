import * as assert from 'node:assert/strict';
import { ChildProcessWithoutNullStreams, spawn, SpawnOptionsWithoutStdio } from 'node:child_process';
import { EventEmitter } from 'node:events';
import * as path from 'node:path';
import { PassThrough } from 'node:stream';
import { test } from 'node:test';
import { BackendClient, BackendSettings, RequestCancelledError } from '../backendClient';
import { AnalysisRequest, AnalysisResponse } from '../backendProtocol';

const settings: BackendSettings = {
	pythonExecutable: '/configured Python/python',
	backendPath: path.resolve(__dirname, '../../..'),
	analysisTimeoutMs: 1000,
};
const request: AnalysisRequest = {
	protocol_version: 1, request_id: '17', method: 'analyze',
	document_uri: 'untitled:Unsaved-1', document_path: path.join(settings.backendPath, 'Unsaved.dl'),
	document_version: 17, text: '# unsaved \u00e9\ud83d\ude00; "quotes" $(unsafe) `unsafe` & unsafe\n',
};

function response(): AnalysisResponse {
	return {
		protocol_version: 1, request_id: request.request_id, document_uri: request.document_uri,
		document_version: request.document_version, ok: true,
		result: { analysis: {
			document_path: request.document_path, document_version: 17,
			diagnostics: [], datasets: [], statements: [],
		}, cursor: null },
	};
}

class FakeChild extends EventEmitter {
	stdin = new PassThrough();
	stdout = new PassThrough();
	stderr = new PassThrough();
	input = '';
	kills: (NodeJS.Signals | undefined)[] = [];
	closed = false;
	constructor() {
		super();
		this.stdin.on('data', chunk => { this.input += chunk.toString(); });
	}
	kill(signal?: NodeJS.Signals): boolean {
		this.kills.push(signal);
		queueMicrotask(() => this.close(null, signal ?? 'SIGTERM'));
		return true;
	}
	close(code: number | null = 0, signal: NodeJS.Signals | null = null): void {
		if (!this.closed) { this.closed = true; this.emit('close', code, signal); }
	}
	finish(value: AnalysisResponse = response(), code = 0): void {
		this.stdout.write(JSON.stringify(value));
		this.close(code);
	}
	asChild(): ChildProcessWithoutNullStreams { return this as unknown as ChildProcessWithoutNullStreams; }
	assertClean(): void {
		assert.equal(this.listenerCount('error'), 0);
		assert.equal(this.listenerCount('close'), 0);
		assert.equal(this.stdin.listenerCount('error'), 0);
		assert.equal(this.stdout.listenerCount('data'), 0);
		assert.equal(this.stdout.listenerCount('error'), 0);
		assert.equal(this.stderr.listenerCount('data'), 0);
		assert.equal(this.stderr.listenerCount('error'), 0);
	}
}

function harness(overrides: Partial<BackendSettings> = {}) {
	const child = new FakeChild();
	const log: string[] = [];
	let launched: { command: string; args: string[]; options: SpawnOptionsWithoutStdio } | undefined;
	const client = new BackendClient(() => true, text => log.push(text), (command, args, options) => {
		launched = { command, args, options };
		return child.asChild();
	});
	const abort = new AbortController();
	const promise = client.request(request, { ...settings, ...overrides }, abort.signal);
	return { child, client, log, abort, promise, launched };
}

test('spawn uses configured paths, fixed argument array, no shell, and JSON stdin', async () => {
	const run = harness();
	assert.equal(run.launched!.command, settings.pythonExecutable);
	assert.deepEqual(run.launched!.args, ['-u', '-m', 'src.editor.bridge']);
	assert.equal(run.launched!.options.shell, false);
	assert.equal(run.launched!.options.windowsHide, true);
	assert.equal(run.launched!.options.cwd, settings.backendPath);
	assert.deepEqual(JSON.parse(run.child.input), request);
	run.child.stderr.write('backend log\n');
	const json = JSON.stringify(response());
	run.child.stdout.write(json.slice(0, 30));
	run.child.stdout.write(json.slice(30) + '\n');
	run.child.close();
	assert.deepEqual(await run.promise, response().result);
	assert.deepEqual(run.log, ['backend log\n']);
	run.child.assertClean();
	run.client.dispose();
});

for (const [name, mutate] of [
	['request ID', (value: AnalysisResponse) => { value.request_id = 'old'; }],
	['document URI', (value: AnalysisResponse) => { value.document_uri = 'unrelated'; }],
	['document version', (value: AnalysisResponse) => { value.document_version = 1; }],
	['analysis version', (value: AnalysisResponse) => { value.result!.analysis.document_version = 1; }],
] as const) {
	test(`rejects mismatched ${name}`, async () => {
		const run = harness();
		const value = response();
		mutate(value);
		run.child.finish(value);
		await assert.rejects(run.promise, /match|Invalid analysis/);
		run.child.assertClean();
	});
}

test('rejects malformed stdout and reports stderr startup detail', async () => {
	const run = harness();
	run.child.stderr.write('ModuleNotFoundError: backend not installed\n');
	run.child.stdout.write('not JSON\n{}');
	run.child.close(1);
	await assert.rejects(run.promise, /ModuleNotFoundError.*backend installation/);
	run.child.assertClean();
});

test('reports an executable startup error without unhandled child errors', async () => {
	const run = harness();
	run.child.emit('error', new Error('spawn ENOENT'));
	await assert.rejects(run.promise, /ENOENT.*datalang.pythonExecutable/);
	run.child.assertClean();
});

test('reports a missing response on nonzero process exit', async () => {
	const run = harness();
	run.child.stderr.write('SyntaxError: Python is too old\n');
	run.child.close(1);
	await assert.rejects(run.promise, /No JSON response.*Python is too old/);
	run.child.assertClean();
});

test('structured backend errors are reported even with a nonzero exit code', async () => {
	const run = harness();
	run.child.finish({ ...response(), ok: false, result: undefined,
		error: { code: 'backend_error', message: 'Check the backend installation.' } }, 1);
	await assert.rejects(run.promise, /Check the backend installation/);
	run.child.assertClean();
});

test('timeout kills the process and removes listeners', async () => {
	const run = harness({ analysisTimeoutMs: 15 });
	await assert.rejects(run.promise, /timed out after 15 ms/);
	assert.equal(run.child.kills.length, 1);
	run.child.assertClean();
});

test('cancellation kills obsolete work and removes listeners', async () => {
	const run = harness();
	run.abort.abort();
	await assert.rejects(run.promise, RequestCancelledError);
	assert.equal(run.child.kills.length, 1);
	run.child.assertClean();
});

test('dispose terminates requests and prevents subsequent starts', async () => {
	const run = harness();
	run.client.dispose();
	run.client.dispose();
	await assert.rejects(run.promise, RequestCancelledError);
	await assert.rejects(run.client.request(request, settings, new AbortController().signal), RequestCancelledError);
	run.child.assertClean();
});

test('workspace trust is checked immediately before spawn', async () => {
	let launches = 0;
	const client = new BackendClient(() => false, () => {}, () => { launches++; throw new Error('must not spawn'); });
	await assert.rejects(client.request(request, settings, new AbortController().signal), /Trust this workspace/);
	assert.equal(launches, 0);
});

test('reports invalid backend paths and synchronous spawn errors clearly', async () => {
	const client = new BackendClient(() => true, () => {}, () => { throw new Error('injected startup failure'); });
	await assert.rejects(client.request(request, { ...settings, backendPath: 'relative' }, new AbortController().signal), /datalang.backendPath/);
	await assert.rejects(client.request(request, settings, new AbortController().signal), /Cannot start Python.*datalang.pythonExecutable/);
});

test('real child process exchanges one UTF-8 JSON request and response over pipes', async () => {
	const fixture = `let input = ''; process.stdin.setEncoding('utf8');
process.stdin.on('data', chunk => input += chunk);
process.stdin.on('end', () => {
 const r = JSON.parse(input);
 process.stderr.write('fixture log\\n');
 process.stdout.write(JSON.stringify({protocol_version: 1, request_id: r.request_id,
 document_uri: r.document_uri, document_version: r.document_version, ok: true,
 result: {analysis: {document_path: r.document_path, document_version: r.document_version,
 diagnostics: [], datasets: [r.text], statements: []}, cursor: null}}) + '\\n');
});`;
	const logs: string[] = [];
	const client = new BackendClient(() => true, text => logs.push(text), (_command, _args, options) =>
		spawn(process.execPath, ['-e', fixture], options));
	const result = await client.request(request, settings, new AbortController().signal);
	assert.deepEqual(result.analysis.datasets, [request.text]);
	assert.equal(logs.join(''), 'fixture log\n');
	client.dispose();
});
