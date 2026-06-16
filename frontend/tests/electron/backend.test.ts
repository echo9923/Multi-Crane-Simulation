import { describe, expect, it } from "vitest";
import {
  escapeJsonForInlineScript,
  isPathInsideAllowedRoots,
  makeBackendLaunch,
  resolvePythonPath,
  runtimeScriptTag,
  withRuntimeScript,
} from "../../electron/backend.mjs";

describe("electron backend helpers", () => {
  it("resolves platform-specific venv python path", () => {
    expect(resolvePythonPath("/repo", "darwin")).toBe("/repo/.venv/bin/python");
    expect(resolvePythonPath("/repo", "linux")).toBe("/repo/.venv/bin/python");
    expect(resolvePythonPath("C:/repo", "win32")).toBe("C:/repo/.venv/Scripts/python.exe");
    expect(resolvePythonPath("C:\\repo", "win32")).toBe("C:\\repo\\.venv\\Scripts\\python.exe");
  });

  it("allows paths inside configured safe roots only", () => {
    expect(isPathInsideAllowedRoots("/repo/runs/run-001", ["/repo"])).toBe(true);
    expect(isPathInsideAllowedRoots("/repo", ["/repo"])).toBe(true);
    expect(isPathInsideAllowedRoots("/repo-other/run-001", ["/repo"])).toBe(false);
    expect(isPathInsideAllowedRoots("/tmp/run-001", ["/repo", "/home/userData"])).toBe(false);
  });

  it("builds the uvicorn backend launch command", () => {
    const launch = makeBackendLaunch({
      projectRoot: "/repo",
      pythonPath: "/repo/.venv/bin/python",
      port: 8765,
    });

    expect(launch.command).toBe("/repo/.venv/bin/python");
    expect(launch.args).toEqual([
      "-m",
      "uvicorn",
      "backend.app.main:app",
      "--host",
      "127.0.0.1",
      "--port",
      "8765",
    ]);
    expect(launch.env.MULTI_CRANE_BACKEND_PORT).toBe("8765");
  });

  it("injects desktop runtime config into index html", () => {
    const html = "<html><head></head><body><div id=\"root\"></div></body></html>";
    const tag = runtimeScriptTag({ port: 8765 });
    const injected = withRuntimeScript(html, { port: 8765 });
    expect(tag).toContain("__MULTI_CRANE_DESKTOP__");
    expect(tag).toContain("8765");
    expect(injected).toContain("__MULTI_CRANE_DESKTOP__");
  });

  it("emits a parseable desktop runtime config script without raw less-than characters in the payload", () => {
    const tag = runtimeScriptTag({ port: 8765 });
    const match = tag.match(/^<script>window\.__MULTI_CRANE_DESKTOP__=(.*);<\/script>$/);

    expect(match).not.toBeNull();
    expect(match?.[1]).not.toContain("<");
    expect(JSON.parse(match?.[1] ?? "{}")).toEqual({
      apiBase: "http://127.0.0.1:8765",
      wsBase: "ws://127.0.0.1:8765/ws",
      backendPort: 8765,
      mode: "desktop",
    });
  });

  it("escapes less-than characters in inline script JSON payloads", () => {
    const payload = escapeJsonForInlineScript({ closingTag: "</script>" });

    expect(payload).not.toContain("<");
    expect(JSON.parse(payload)).toEqual({ closingTag: "</script>" });
  });

  it("prepends the runtime script when index html has no head closing tag", () => {
    const html = "<html><body><div id=\"root\"></div></body></html>";
    const injected = withRuntimeScript(html, { port: 8765 });

    expect(injected.startsWith("<script>window.__MULTI_CRANE_DESKTOP__=")).toBe(true);
    expect(injected).toContain(html);
  });

  it("rewrites Vite root-relative built assets to the desktop dist asset directory", () => {
    const html = `<!doctype html>
<html>
  <head>
    <script type="module" crossorigin src="/assets/index.js"></script>
    <link rel="stylesheet" crossorigin href="/assets/index.css">
  </head>
  <body><div id="root"></div></body>
</html>`;

    const injected = withRuntimeScript(html, {
      port: 8765,
      assetBaseUrl: "file:///repo/frontend/dist/",
    });

    expect(injected).toContain('src="file:///repo/frontend/dist/assets/index.js"');
    expect(injected).toContain('href="file:///repo/frontend/dist/assets/index.css"');
    expect(injected).not.toContain('src="/assets/index.js"');
    expect(injected).not.toContain('href="/assets/index.css"');
  });
});
