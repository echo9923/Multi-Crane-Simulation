import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
  escapeJsonForInlineScript,
  isPathInsideAllowedRoots,
  makeBackendLaunch,
  resolvePythonPath,
  runtimeScriptTag,
  rendererIndexUrl,
  startRendererServer,
  withRuntimeScript,
} from "../../electron/backend.mjs";

describe("electron backend helpers", () => {
  const rendererServers: Array<{ close: () => Promise<void> }> = [];

  afterEach(async () => {
    await Promise.all(rendererServers.splice(0).map((server) => server.close()));
  });

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

  it("leaves Vite root-relative built assets unchanged for loopback HTTP serving", () => {
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
    });

    expect(injected).toContain('src="/assets/index.js"');
    expect(injected).toContain('href="/assets/index.css"');
  });

  it("builds the loopback renderer desktop index URL", () => {
    expect(rendererIndexUrl(61234)).toBe("http://127.0.0.1:61234/desktop-index.html");
  });

  it("serves built renderer files from a temp dist directory", async () => {
    const distRoot = await fs.mkdtemp(path.join(os.tmpdir(), "multi-crane-renderer-"));
    await fs.mkdir(path.join(distRoot, "assets"));
    await fs.writeFile(path.join(distRoot, "desktop-index.html"), "<!doctype html><h1>Desktop</h1>", "utf8");
    await fs.writeFile(path.join(distRoot, "assets", "index.js"), "console.log('desktop');", "utf8");

    const server = await startRendererServer({ distRoot, port: 0 });
    rendererServers.push(server);

    const indexResponse = await fetch(rendererIndexUrl(server.port));
    expect(indexResponse.status).toBe(200);
    expect(indexResponse.headers.get("content-type")).toContain("text/html");
    expect(await indexResponse.text()).toContain("<h1>Desktop</h1>");

    const assetResponse = await fetch(`http://127.0.0.1:${server.port}/assets/index.js`);
    expect(assetResponse.status).toBe(200);
    expect(assetResponse.headers.get("content-type")).toContain("text/javascript");
    expect(await assetResponse.text()).toContain("console.log('desktop');");
  });

  it("rejects missing files and traversal attempts from the renderer server", async () => {
    const tempRoot = await fs.mkdtemp(path.join(os.tmpdir(), "multi-crane-renderer-"));
    const distRoot = path.join(tempRoot, "dist");
    await fs.mkdir(distRoot);
    await fs.mkdir(path.join(distRoot, "assets"));
    await fs.writeFile(path.join(distRoot, "desktop-index.html"), "<!doctype html><h1>Desktop</h1>", "utf8");
    await fs.writeFile(path.join(tempRoot, "package.json"), "{\"private\":true}", "utf8");

    const server = await startRendererServer({ distRoot, port: 0 });
    rendererServers.push(server);

    const missingResponse = await fetch(`http://127.0.0.1:${server.port}/assets/missing.js`);
    expect(missingResponse.status).toBe(404);

    const traversalResponse = await fetch(`http://127.0.0.1:${server.port}/../package.json`);
    expect(traversalResponse.status).toBe(404);

    const encodedTraversalResponse = await fetch(`http://127.0.0.1:${server.port}/%2e%2e/package.json`);
    expect(encodedTraversalResponse.status).toBe(404);
    expect(await encodedTraversalResponse.text()).not.toContain("\"private\":true");
  });
});
