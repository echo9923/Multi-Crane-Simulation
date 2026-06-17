const { app, BrowserWindow, ipcMain, shell } = require("electron/main");
const fs = require("node:fs/promises");
const path = require("node:path");
const { pathToFileURL } = require("node:url");

const electronRoot = __dirname;
const frontendRoot = path.resolve(electronRoot, "..");
const preloadPath = path.join(electronRoot, "preload.cjs");
const backendLogs = [];

let backendHelpers;
let backendChild;
let backendPort;
let desktopUserDataPath;
let mainWindow;
let projectRoot;
let rendererServer;
let resourceRoot;
let isQuitting = false;

app.whenReady().then(async () => {
  try {
    backendHelpers = await loadBackendHelpers();
    const desktopRoots = {
      electronRoot,
      isPackaged: app.isPackaged,
      resourcesPath: process.resourcesPath,
    };
    resourceRoot = backendHelpers.resolveResourceRoot(desktopRoots);
    projectRoot = backendHelpers.resolveProjectRoot(desktopRoots);
    registerIpcHandlers();

    desktopUserDataPath = app.getPath("userData");
    const port = await backendHelpers.findAvailablePort();
    const pythonPath = backendHelpers.resolvePythonPath({
      fallbackProjectRoot: process.env.MULTI_CRANE_DEV_PROJECT_ROOT,
      projectRoot,
      resourceRoot,
      isPackaged: app.isPackaged,
      env: process.env,
    });
    backendPort = port;

    backendChild = backendHelpers.startBackend({
      projectRoot,
      pythonPath,
      port,
      onLog: (message, stream) => appendBackendLog(stream, message),
    });
    trackBackendExit(backendChild);

    await backendHelpers.waitForHealth({ port });
    mainWindow = await createMainWindow(port);
  } catch (error) {
    await stopRendererServer();
    stopBackend();
    mainWindow = createFailureWindow(error);
  }

  app.on("activate", async () => {
    if (BrowserWindow.getAllWindows().length === 0 && !mainWindow) {
      mainWindow = await createMainWindowFromExistingBackend();
    }
  });
});

app.on("before-quit", () => {
  isQuitting = true;
  void stopRendererServer().catch((error) => {
    appendBackendLog("stderr", `Renderer server shutdown failed: ${error?.message ?? String(error)}\n`);
  });
  stopBackend();
});

app.on("window-all-closed", () => {
  mainWindow = undefined;
  if (process.platform !== "darwin") {
    app.quit();
  }
});

async function loadBackendHelpers() {
  return import(pathToFileURL(path.join(electronRoot, "backend.mjs")).href);
}

function registerIpcHandlers() {
  ipcMain.handle("desktop:openPath", async (_event, targetPath) => {
    if (typeof targetPath !== "string" || targetPath.trim().length === 0) {
      return { ok: false, error: "Path must be a non-empty string." };
    }

    const allowedRoots = [projectRoot, desktopUserDataPath].filter(Boolean);
    const resolvedTargetPath = path.resolve(targetPath);
    if (!backendHelpers.isPathInsideAllowedRoots(resolvedTargetPath, allowedRoots)) {
      return { ok: false, error: "path is outside allowed roots" };
    }

    const error = await shell.openPath(resolvedTargetPath);
    return error ? { ok: false, error } : { ok: true };
  });
}

async function createMainWindow(port) {
  const window = new BrowserWindow({
    width: 1440,
    height: 920,
    minWidth: 1180,
    minHeight: 760,
    title: "Multi Crane Workbench",
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      preload: preloadPath,
    },
  });

  window.on("closed", () => {
    if (!isQuitting) {
      mainWindow = undefined;
    }
  });

  if (process.env.VITE_DEV_SERVER_URL) {
    await loadDevServer(window, port);
  } else {
    await loadBuiltIndex(window, port);
  }

  return window;
}

async function createMainWindowFromExistingBackend() {
  if (!backendChild || backendChild.exitCode !== null || backendChild.signalCode !== null || !backendPort) {
    return createFailureWindow(new Error("Backend is not running."));
  }

  return createMainWindow(backendPort);
}

async function loadDevServer(window, port) {
  const url = new URL(process.env.VITE_DEV_SERVER_URL);
  url.searchParams.set("desktopApiBase", `http://127.0.0.1:${port}`);
  url.searchParams.set("desktopWsBase", `ws://127.0.0.1:${port}/ws`);
  url.searchParams.set("desktopBackendPort", String(port));
  await window.loadURL(url.toString());
}

async function loadBuiltIndex(window, port) {
  const distPath = path.join(frontendRoot, "dist");
  const indexPath = path.join(distPath, "index.html");
  const html = await fs.readFile(indexPath, "utf8");
  const injectedHtml = backendHelpers.withRuntimeScript(html, { port });

  if (!rendererServer) {
    rendererServer = await backendHelpers.startRendererServer({ distRoot: distPath, desktopIndexHtml: injectedHtml });
  }
  await window.loadURL(backendHelpers.rendererIndexUrl(rendererServer.port));
}

function trackBackendExit(child) {
  child.once("exit", () => {
    if (backendChild === child) {
      backendChild = undefined;
      backendPort = undefined;
    }
  });
}

function stopBackend() {
  const child = backendChild;
  backendChild = undefined;
  backendPort = undefined;
  if (child && !child.killed && child.exitCode === null && child.signalCode === null) {
    child.kill();
  }
}

function stopRendererServer() {
  const server = rendererServer;
  rendererServer = undefined;
  if (!server) {
    return Promise.resolve();
  }
  return server.close();
}

function createFailureWindow(error) {
  const window = new BrowserWindow({
    width: 980,
    height: 720,
    title: "Multi Crane Workbench - Startup Error",
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  window.on("closed", () => {
    if (!isQuitting) {
      mainWindow = undefined;
    }
  });

  const message = escapeHtml(error?.stack ?? error?.message ?? String(error));
  const logs = escapeHtml(backendLogs.join(""));
  const html = `<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Multi Crane Workbench - Startup Error</title>
  <style>
    body { font-family: system-ui, sans-serif; margin: 32px; color: #111827; background: #f8fafc; }
    h1 { font-size: 24px; margin-bottom: 16px; }
    pre { white-space: pre-wrap; padding: 16px; background: #111827; color: #f9fafb; border-radius: 6px; overflow: auto; }
  </style>
</head>
<body>
  <h1>Backend startup failed</h1>
  <pre>${message}</pre>
  <h2>Backend logs</h2>
  <pre>${logs || "No backend output captured."}</pre>
</body>
</html>`;

  window.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(html)}`);
  return window;
}

function appendBackendLog(stream, message) {
  backendLogs.push(`[${stream}] ${message}`);
  while (backendLogs.length > 200) {
    backendLogs.shift();
  }
}

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
