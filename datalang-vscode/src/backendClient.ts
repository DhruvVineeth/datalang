import { spawn, ChildProcessWithoutNullStreams, SpawnOptionsWithoutStdio } from 'node:child_process';
import { existsSync } from 'node:fs';
import * as path from 'node:path';
import { AnalysisRequest, AnalysisPayloadResult, parseResponse } from './backendProtocol';

export interface BackendSettings {
	pythonExecutable: string;
	backendPath: string;
	analysisTimeoutMs: number;
}

type Launch = (command: string, args: string[], options: SpawnOptionsWithoutStdio) => ChildProcessWithoutNullStreams;

export class RequestCancelledError extends Error {
	constructor() {
		super('DataLang analysis was cancelled.');
	}
}

/** Each request owns one process. No document data is passed as an argument. */
export class BackendClient {
	private readonly running = new Set<{ cancel(): void }>();
	private disposed = false;

	constructor(
		private readonly canSpawn: () => boolean,
		private readonly log: (text: string) => void,
		private readonly launch: Launch = spawn,
	) {}

	async request(request: AnalysisRequest, settings: BackendSettings, signal: AbortSignal): Promise<AnalysisPayloadResult> {
		if (this.disposed || signal.aborted) {
			throw new RequestCancelledError();
		}
		if (!settings.pythonExecutable.trim()) {
			throw new Error('Set datalang.pythonExecutable to a Python executable, without arguments.');
		}
		if (!path.isAbsolute(settings.backendPath)
			|| !existsSync(path.join(settings.backendPath, 'src', 'editor', 'bridge.py'))) {
			throw new Error('Set datalang.backendPath to an absolute DataLang repository root containing src/editor/bridge.py.');
		}
		if (!Number.isFinite(settings.analysisTimeoutMs) || settings.analysisTimeoutMs <= 0) {
			throw new Error('datalang.analysisTimeoutMs must be positive.');
		}
		return new Promise((resolve, reject) => {
			// Check trust immediately before the actual spawn, including delayed requests.
			if (!this.canSpawn()) {
				reject(new Error('Trust this workspace before starting the DataLang Python backend.'));
				return;
			}
			let child: ChildProcessWithoutNullStreams;
			try {
				child = this.launch(settings.pythonExecutable, ['-u', '-m', 'src.editor.bridge'], {
					cwd: settings.backendPath,
					shell: false,
					windowsHide: true,
					env: { ...process.env, PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8' },
				});
			} catch (error) {
				reject(new Error(`Cannot start Python '${settings.pythonExecutable}': ${String(error)}. Check datalang.pythonExecutable.`));
				return;
			}
			let settled = false;
			let stdout = '';
			let stdoutBytes = 0;
			let stderrTail = '';
			let forceKill: NodeJS.Timeout | undefined;
			const finish = (error?: Error, result?: AnalysisPayloadResult) => {
				if (settled) { return; }
				settled = true;
				clearTimeout(timeout);
				signal.removeEventListener('abort', onAbort);
				if (error) { reject(error); } else { resolve(result!); }
			};
			const stop = (error: Error) => {
				if (settled) { return; }
				finish(error);
				child.kill();
				forceKill = setTimeout(() => child.kill('SIGKILL'), 1000);
				forceKill.unref();
			};
			const onAbort = () => stop(new RequestCancelledError());
			const onError = (error: Error) => stop(new Error(
				`Cannot start or communicate with Python '${settings.pythonExecutable}': ${error.message}. Check datalang.pythonExecutable and backend installation.`,
			));
			const onStdout = (chunk: string) => {
				stdoutBytes += Buffer.byteLength(chunk, 'utf8');
				if (stdoutBytes > 16 * 1024 * 1024) {
					stop(new Error('DataLang backend response exceeded 16 MiB.'));
				} else if (!settled) {
					stdout += chunk;
				}
			};
			const onStderr = (chunk: string) => {
				stderrTail = (stderrTail + chunk).slice(-4096);
				this.log(chunk);
			};
			const onClose = (code: number | null, killedBy: NodeJS.Signals | null) => {
				clearTimeout(forceKill);
				this.running.delete(running);
				child.removeListener('error', onError);
				child.removeListener('close', onClose);
				child.stdin.removeListener('error', onError);
				child.stdout.removeListener('error', onError);
				child.stderr.removeListener('error', onError);
				child.stdout.removeListener('data', onStdout);
				child.stderr.removeListener('data', onStderr);
				if (settled) { return; }
				try {
					if (!stdout.trim()) {
						throw new Error('No JSON response was received.');
					}
					const response = parseResponse(stdout, request);
					if (!response.ok) { throw new Error(response.error!.message); }
					if (code !== 0) { throw new Error(`Backend exited with ${code ?? killedBy}.`); }
					finish(undefined, response.result!);
				} catch (error) {
					const detail = stderrTail.trim().split('\n').at(-1)?.slice(-500);
					finish(new Error(`DataLang backend failed: ${(error as Error).message}${detail ? ` ${detail}` : ''} Check backend installation; see DataLang output.`));
				}
			};
			const timeout = setTimeout(() => stop(new Error(
				`DataLang backend timed out after ${settings.analysisTimeoutMs} ms. Check CSV access or increase datalang.analysisTimeoutMs.`,
			)), settings.analysisTimeoutMs);
			const running = { cancel: onAbort };
			this.running.add(running);
			child.stdout.setEncoding('utf8');
			child.stderr.setEncoding('utf8');
			child.on('error', onError);
			child.once('close', onClose);
			child.stdin.on('error', onError);
			child.stdout.on('error', onError);
			child.stderr.on('error', onError);
			child.stdout.on('data', onStdout);
			child.stderr.on('data', onStderr);
			signal.addEventListener('abort', onAbort, { once: true });
			if (signal.aborted) { onAbort(); } else {
				child.stdin.end(JSON.stringify(request), 'utf8');
			}
		});
	}

	dispose(): void {
		if (this.disposed) { return; }
		this.disposed = true;
		for (const running of this.running) { running.cancel(); }
	}
}
