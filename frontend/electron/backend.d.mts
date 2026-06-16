import type { ChildProcessByStdio } from "node:child_process";
import type { Readable } from "node:stream";

export interface BackendLaunch {
  command: string;
  args: string[];
  cwd: string;
  env: NodeJS.ProcessEnv;
}

export interface BackendLaunchOptions {
  projectRoot: string;
  pythonPath: string;
  port: number;
}

export interface HealthWaitOptions {
  port: number;
  timeoutMs?: number;
  intervalMs?: number;
  fetchImpl?: typeof fetch;
}

export interface StartBackendOptions extends BackendLaunchOptions {
  onLog?: (message: string, stream: "stdout" | "stderr") => void;
}

export interface RuntimeScriptOptions {
  port: number;
}

export interface RendererServerOptions {
  distRoot: string;
  port?: number;
}

export interface RendererServer {
  port: number;
  url: string;
  close: () => Promise<void>;
}

export function resolvePythonPath(projectRoot: string, platform?: NodeJS.Platform): string;
export function isPathInsideAllowedRoots(targetPath: string, allowedRoots: string[]): boolean;
export function makeBackendLaunch(options: BackendLaunchOptions): BackendLaunch;
export function findAvailablePort(start?: number, host?: string): Promise<number>;
export function waitForHealth(options: HealthWaitOptions): Promise<Response>;
export function startBackend(options: StartBackendOptions): ChildProcessByStdio<null, Readable, Readable>;
export function rendererIndexUrl(port: number): string;
export function startRendererServer(options: RendererServerOptions): Promise<RendererServer>;
export function escapeJsonForInlineScript(value: unknown): string;
export function runtimeScriptTag(options: RuntimeScriptOptions): string;
export function withRuntimeScript(html: string, options: RuntimeScriptOptions): string;
