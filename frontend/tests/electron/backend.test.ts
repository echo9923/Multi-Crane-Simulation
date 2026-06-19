import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
  escapeJsonForInlineScript,
  isPathInsideAllowedRoots,
  makeBackendLaunch,
  resolveDataRoot,
  resolveProjectRoot,
  resolvePythonPath,
  resolveResourceRoot,
  runtimeScriptTag,
  rendererIndexUrl,
  startRendererServer,
  withRuntimeScript,
} from "../../electron/backend.mjs";
import packageJson from "../../package.json" with { type: "json" };

describe("electron backend helpers", () => {
  const rendererServers: Array<{ close: () => Promise<void> }> = [];
  const desktopIndexHtml = "<!doctype html><h1>Desktop</h1>";

  afterEach(async () => {
    await Promise.all(rendererServers.splice(0).map((server) => server.close()));
  });

  async function createRendererDist() {
    const tempRoot = await fs.mkdtemp(path.join(os.tmpdir(), "multi-crane-renderer-"));
    const distRoot = path.join(tempRoot, "dist");
    await fs.mkdir(distRoot);
    await fs.mkdir(path.join(distRoot, "assets"));
    await fs.writeFile(path.join(distRoot, "desktop-index.html"), desktopIndexHtml, "utf8");
    await fs.writeFile(path.join(distRoot, "assets", "index.js"), "console.log('desktop');", "utf8");
    return { tempRoot, distRoot };
  }

  it("resolves the repo project root in development", () => {
    expect(
      resolveProjectRoot({
        electronRoot: "/repo/frontend/electron",
        isPackaged: false,
        resourcesPath: "/Applications/Multi Crane.app/Contents/Resources",
      }),
    ).toBe("/repo");
  });

  it("resolves packaged project and resource roots from Electron Builder resources", () => {
    const resourcesPath = "/Applications/Multi Crane.app/Contents/Resources";

    expect(
      resolveResourceRoot({
        electronRoot: "/Applications/Multi Crane.app/Contents/Resources/app.asar/electron",
        isPackaged: true,
        resourcesPath,
      }),
    ).toBe(resourcesPath);
    expect(
      resolveProjectRoot({
        electronRoot: "/Applications/Multi Crane.app/Contents/Resources/app.asar/electron",
        isPackaged: true,
        resourcesPath,
      }),
    ).toBe(path.posix.join(resourcesPath, "project"));
  });

  it("resolves packaged writable data root from Electron userData", () => {
    expect(
      resolveDataRoot({
        isPackaged: true,
        projectRoot: "/Applications/Multi Crane.app/Contents/Resources/project",
        userDataPath: "/Users/alice/Library/Application Support/Multi Crane Workbench",
      }),
    ).toBe("/Users/alice/Library/Application Support/Multi Crane Workbench");
    expect(
      resolveDataRoot({
        isPackaged: false,
        projectRoot: "/repo",
        userDataPath: "/Users/alice/Library/Application Support/Multi Crane Workbench",
      }),
    ).toBe("/repo");
  });

  it("resolves platform-specific venv python path", () => {
    expect(resolvePythonPath({ projectRoot: "/repo", platform: "darwin" })).toBe("/repo/.venv/bin/python");
    expect(resolvePythonPath({ projectRoot: "/repo", platform: "linux" })).toBe("/repo/.venv/bin/python");
    expect(resolvePythonPath({ projectRoot: "C:/repo", platform: "win32" })).toBe(
      "C:/repo/.venv/Scripts/python.exe",
    );
    expect(resolvePythonPath({ projectRoot: "C:\\repo", platform: "win32" })).toBe(
      "C:\\repo\\.venv\\Scripts\\python.exe",
    );
  });

  it("prefers an explicit MULTI_CRANE_PYTHON path", () => {
    expect(
      resolvePythonPath({
        projectRoot: "/repo",
        resourceRoot: "/resources",
        env: { MULTI_CRANE_PYTHON: "/opt/python/bin/python" },
        platform: "darwin",
      }),
    ).toBe("/opt/python/bin/python");
  });

  it("supports packaged resource venv when it exists", () => {
    expect(
      resolvePythonPath({
        projectRoot: "/repo",
        resourceRoot: "/resources",
        env: {},
        isPackaged: true,
        pathExists: (candidatePath) => candidatePath === "/resources/.venv/bin/python",
        platform: "darwin",
      }),
    ).toBe("/resources/.venv/bin/python");
  });

  it("falls back to a development checkout venv when the packaged resource venv is missing", () => {
    const resourcesPath = "/Applications/Multi Crane.app/Contents/Resources";
    const desktopRoots = {
      electronRoot: path.join(resourcesPath, "app.asar", "electron"),
      isPackaged: true,
      resourcesPath,
    };

    expect(
      resolvePythonPath({
        fallbackProjectRoot: "/repo",
        projectRoot: resolveProjectRoot(desktopRoots),
        resourceRoot: resolveResourceRoot(desktopRoots),
        env: {},
        isPackaged: true,
        pathExists: (candidatePath) => candidatePath === "/repo/.venv/bin/python",
        platform: "darwin",
      }),
    ).toBe("/repo/.venv/bin/python");
  });

  it("throws a clear packaged runtime error when packaged and fallback venvs are missing", () => {
    const resourcesPath = "/Applications/Multi Crane.app/Contents/Resources";
    const desktopRoots = {
      electronRoot: path.join(resourcesPath, "app.asar", "electron"),
      isPackaged: true,
      resourcesPath,
    };

    expect(() =>
      resolvePythonPath({
        fallbackProjectRoot: "/repo",
        projectRoot: resolveProjectRoot(desktopRoots),
        resourceRoot: resolveResourceRoot(desktopRoots),
        env: {},
        isPackaged: true,
        pathExists: () => false,
        platform: "darwin",
      }),
    ).toThrow(/Packaged Python runtime is missing.*\/Resources\/\.venv\/bin\/python.*\/repo\/\.venv\/bin\/python.*MULTI_CRANE_PYTHON/s);
  });

  it("uses the repo venv in development", () => {
    expect(
      resolvePythonPath({
        projectRoot: "/repo",
        resourceRoot: "/resources",
        env: {},
        isPackaged: false,
        platform: "darwin",
      }),
    ).toBe("/repo/.venv/bin/python");
  });

  it("uses CommonJS Electron entrypoints for reliable Electron API loading", async () => {
    const entrypoints = ["main.cjs", "preload.cjs"];

    for (const entrypoint of entrypoints) {
      const source = await fs.readFile(path.resolve(process.cwd(), "electron", entrypoint), "utf8");

      expect(source).not.toMatch(/import\s+\{[^}]+\}\s+from\s+["']electron["']/);
    }
    expect(await fs.readFile(path.resolve(process.cwd(), "electron", "main.cjs"), "utf8")).toContain(
      'require("electron/main")',
    );
    expect(await fs.readFile(path.resolve(process.cwd(), "electron", "preload.cjs"), "utf8")).toContain(
      'require("electron/renderer")',
    );
  });

  it("configures Electron Builder scripts and resource inclusion rules", () => {
    const unsignedWindowsArgs =
      "--win --config.win.signAndEditExecutable=false --config.win.signExecutable=false";

    expect(packageJson.scripts["desktop:pack"]).toBe(
      `npm run build && electron-builder ${unsignedWindowsArgs} --dir`,
    );
    expect(packageJson.scripts["desktop:dist"]).toBe(
      `npm run build && electron-builder ${unsignedWindowsArgs}`,
    );
    expect(packageJson.scripts.desktop).toBe("electron electron/main.cjs");
    expect(packageJson.scripts["desktop:dev"]).toBe("electron electron/dev.cjs");
    expect(packageJson.main).toBe("electron/main.cjs");
    expect(packageJson.devDependencies).toHaveProperty("electron-builder");

    expect(packageJson.build.files).toEqual(
      expect.arrayContaining(["dist/**", "electron/**", "package.json"]),
    );
    expect(packageJson.build.extraResources).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ from: "../backend", to: "project/backend" }),
        expect.objectContaining({ from: "../configs", to: "project/configs" }),
        expect.objectContaining({ from: "../.venv", to: ".venv" }),
      ]),
    );

    const copiedResourceFilters = packageJson.build.extraResources
      .filter((resource) => ["../backend", "../configs", "../.venv"].includes(resource.from))
      .map((resource) => resource.filter);
    const venvResourceFilter = packageJson.build.extraResources.find(
      (resource) => resource.from === "../.venv",
    )?.filter;
    const requiredCommonExclusions = [
      "!**/.env*",
      "!**/.claude/**",
      "!**/.worktrees/**",
      "!**/runs/**",
      "!**/__pycache__/**",
      "!**/*.pyc",
      "!**/.pytest_cache/**",
      "!**/*.p12",
      "!**/*.key",
      "!**/*token*.json",
      "!**/*credentials*.json",
    ];
    const requiredProjectExclusions = [...requiredCommonExclusions, "!**/*.pem"];

    expect(copiedResourceFilters).toHaveLength(3);
    for (const filter of copiedResourceFilters) {
      expect(filter).toEqual(expect.arrayContaining(requiredCommonExclusions));
      expect(filter).not.toContain("!**/*secret*");
    }
    expect(venvResourceFilter).not.toContain("!**/*.pem");
    expect(venvResourceFilter).toEqual(expect.arrayContaining(["**/certifi/cacert.pem"]));
    for (const projectResource of packageJson.build.extraResources.filter((resource) =>
      ["../backend", "../configs"].includes(resource.from),
    )) {
      expect(projectResource.filter).toEqual(expect.arrayContaining(requiredProjectExclusions));
    }
    expect(packageJson.build.win.target).toEqual(["dir"]);
    expect(packageJson.build.win.signAndEditExecutable).toBe(false);
    expect(packageJson.build.win.signExecutable).toBe(false);
    expect(packageJson.build.mac.extendInfo.LSEnvironment.ELECTRON_RUN_AS_NODE).toBe("");
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
    expect(launch.cwd).toBe("/repo");
    expect(launch.env.MULTI_CRANE_BACKEND_PORT).toBe("8765");
    expect(launch.env.MULTI_CRANE_PROJECT_ROOT).toBe("/repo");
    expect(launch.env.MULTI_CRANE_DATA_ROOT).toBe("/repo");
  });

  it("launches packaged backend from a writable data root while importing packaged project code", () => {
    const launch = makeBackendLaunch({
      projectRoot: "C:\\Program Files\\Multi Crane\\resources\\project",
      dataRoot: "C:\\Users\\Alice\\AppData\\Roaming\\Multi Crane Workbench",
      pythonPath: "C:\\Program Files\\Multi Crane\\resources\\.venv\\Scripts\\python.exe",
      port: 8765,
    });

    expect(launch.cwd).toBe("C:\\Users\\Alice\\AppData\\Roaming\\Multi Crane Workbench");
    expect(launch.env.MULTI_CRANE_PROJECT_ROOT).toBe("C:\\Program Files\\Multi Crane\\resources\\project");
    expect(launch.env.MULTI_CRANE_DATA_ROOT).toBe("C:\\Users\\Alice\\AppData\\Roaming\\Multi Crane Workbench");
    expect(launch.env.PYTHONPATH).toBeDefined();
    expect(launch.env.PYTHONPATH!.split(path.delimiter)).toContain(
      "C:\\Program Files\\Multi Crane\\resources\\project",
    );
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
    const { distRoot } = await createRendererDist();

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

  it("serves the desktop index for extensionless HTML navigation routes", async () => {
    const { distRoot } = await createRendererDist();

    const server = await startRendererServer({ distRoot, port: 0 });
    rendererServers.push(server);

    const configResponse = await fetch(`http://127.0.0.1:${server.port}/config`, {
      headers: { Accept: "text/html" },
    });
    expect(configResponse.status).toBe(200);
    expect(configResponse.headers.get("content-type")).toContain("text/html");
    expect(await configResponse.text()).toContain(desktopIndexHtml);

    const runResponse = await fetch(`http://127.0.0.1:${server.port}/run`, {
      headers: { Accept: "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8" },
    });
    expect(runResponse.status).toBe(200);
    expect(await runResponse.text()).toContain(desktopIndexHtml);
  });

  it("rejects missing files and traversal attempts from the renderer server", async () => {
    const { tempRoot, distRoot } = await createRendererDist();
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
