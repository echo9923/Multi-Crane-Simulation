import { spawn } from "node:child_process";
import fs from "node:fs";
import fsp from "node:fs/promises";
import http from "node:http";
import net from "node:net";
import path from "node:path";

export function resolveResourceRoot({ electronRoot, isPackaged = false, resourcesPath } = {}) {
  if (isPackaged && typeof resourcesPath === "string" && resourcesPath.trim().length > 0) {
    return resourcesPath;
  }
  if (typeof electronRoot !== "string" || electronRoot.trim().length === 0) {
    throw new Error("electronRoot is required to resolve desktop resources.");
  }
  return pathApiForRoot(electronRoot).resolve(electronRoot, "..", "..");
}

export function resolveProjectRoot({ electronRoot, isPackaged = false, resourcesPath } = {}) {
  const resourceRoot = resolveResourceRoot({ electronRoot, isPackaged, resourcesPath });
  if (isPackaged) {
    return pathApiForRoot(resourceRoot).join(resourceRoot, "project");
  }
  return resourceRoot;
}

export function resolvePythonPath(options, legacyPlatform = process.platform) {
  if (typeof options === "string") {
    return venvPythonPath(options, legacyPlatform);
  }

  const {
    env = process.env,
    fallbackProjectRoot,
    isPackaged = false,
    pathExists = fs.existsSync,
    platform = process.platform,
    projectRoot,
    resourceRoot,
  } = options ?? {};
  const explicitPythonPath = env.MULTI_CRANE_PYTHON?.trim();
  if (explicitPythonPath) {
    return explicitPythonPath;
  }
  if (isPackaged && typeof resourceRoot === "string" && resourceRoot.trim().length > 0) {
    const packagedPythonPath = venvPythonPath(resourceRoot, platform);
    if (pathExists(packagedPythonPath)) {
      return packagedPythonPath;
    }
    if (typeof fallbackProjectRoot === "string" && fallbackProjectRoot.trim().length > 0) {
      const fallbackPythonPath = venvPythonPath(fallbackProjectRoot, platform);
      if (pathExists(fallbackPythonPath)) {
        return fallbackPythonPath;
      }
      throw new Error(
        `Packaged Python runtime is missing at ${packagedPythonPath}; fallback Python runtime is missing at ${fallbackPythonPath}. ` +
          "Set MULTI_CRANE_PYTHON to an existing Python executable to launch the desktop backend.",
      );
    }
    throw new Error(
      `Packaged Python runtime is missing at ${packagedPythonPath}. ` +
        "Set MULTI_CRANE_PYTHON to an existing Python executable to launch the desktop backend.",
    );
  }
  return venvPythonPath(projectRoot, platform);
}

function venvPythonPath(projectRoot, platform = process.platform) {
  if (typeof projectRoot !== "string" || projectRoot.trim().length === 0) {
    throw new Error("projectRoot is required to resolve the Python executable.");
  }
  if (platform === "win32") {
    if (projectRoot.includes("\\")) {
      return path.win32.join(projectRoot, ".venv", "Scripts", "python.exe");
    }
    return path.posix.join(projectRoot, ".venv", "Scripts", "python.exe");
  }
  return path.posix.join(projectRoot, ".venv", "bin", "python");
}

function pathApiForRoot(rootPath) {
  if (/^[A-Za-z]:[\\/]/.test(rootPath) || rootPath.includes("\\")) {
    return path.win32;
  }
  if (rootPath.startsWith("/")) {
    return path.posix;
  }
  return path;
}

export function isPathInsideAllowedRoots(targetPath, allowedRoots) {
  if (typeof targetPath !== "string" || targetPath.trim().length === 0) {
    return false;
  }

  const resolvedTargetPath = path.resolve(targetPath);
  return allowedRoots.some((root) => {
    if (typeof root !== "string" || root.trim().length === 0) {
      return false;
    }

    const resolvedRoot = path.resolve(root);
    const relativePath = path.relative(resolvedRoot, resolvedTargetPath);
    return relativePath === "" || (!relativePath.startsWith("..") && !path.isAbsolute(relativePath));
  });
}

export function makeBackendLaunch({ projectRoot, pythonPath, port }) {
  const portString = String(port);
  return {
    command: pythonPath,
    args: [
      "-m",
      "uvicorn",
      "backend.app.main:app",
      "--host",
      "127.0.0.1",
      "--port",
      portString,
    ],
    cwd: projectRoot,
    env: {
      ...process.env,
      MULTI_CRANE_BACKEND_PORT: portString,
    },
  };
}

export async function findAvailablePort(start = 8765, host = "127.0.0.1") {
  for (let port = start; port < start + 100; port += 1) {
    const available = await canListen(port, host);
    if (available) {
      return port;
    }
  }
  throw new Error(`No available port found from ${start} to ${start + 99}`);
}

export async function waitForHealth({ port, timeoutMs = 15000, intervalMs = 250, fetchImpl = fetch }) {
  const startedAt = Date.now();
  const url = `http://127.0.0.1:${port}/health`;
  let lastError;

  while (Date.now() - startedAt < timeoutMs) {
    try {
      const response = await fetchImpl(url);
      if (response.ok) {
        return response;
      }
      lastError = new Error(`Health check returned ${response.status}`);
    } catch (error) {
      lastError = error;
    }
    await delay(intervalMs);
  }

  throw new Error(`Backend health check timed out after ${timeoutMs}ms: ${lastError?.message ?? "no response"}`);
}

export function startBackend({ projectRoot, pythonPath, port, onLog }) {
  const launch = makeBackendLaunch({ projectRoot, pythonPath, port });
  const child = spawn(launch.command, launch.args, {
    cwd: launch.cwd,
    env: launch.env,
    stdio: ["ignore", "pipe", "pipe"],
  });

  child.stdout?.on("data", (chunk) => {
    onLog?.(String(chunk), "stdout");
  });
  child.stderr?.on("data", (chunk) => {
    onLog?.(String(chunk), "stderr");
  });
  child.on("error", (error) => {
    onLog?.(`${error.message}\n`, "stderr");
  });

  return child;
}

export function runtimeScriptTag({ port }) {
  const config = {
    apiBase: `http://127.0.0.1:${port}`,
    wsBase: `ws://127.0.0.1:${port}/ws`,
    backendPort: port,
    mode: "desktop",
  };
  return `<script>window.__MULTI_CRANE_DESKTOP__=${escapeJsonForInlineScript(config)};</script>`;
}

export function escapeJsonForInlineScript(value) {
  return JSON.stringify(value).replaceAll("<", "\\u003c");
}

export function withRuntimeScript(html, options) {
  const { port } = options;
  const tag = runtimeScriptTag({ port });
  if (html.includes("</head>")) {
    return html.replace("</head>", `${tag}</head>`);
  }
  return `${tag}${html}`;
}

export function rendererIndexUrl(port) {
  return `http://127.0.0.1:${port}/desktop-index.html`;
}

export async function startRendererServer({ distRoot, port = 0, desktopIndexHtml } = {}) {
  const resolvedDistRoot = path.resolve(distRoot);
  const server = http.createServer((request, response) => {
    serveRendererRequest({ request, response, distRoot: resolvedDistRoot, desktopIndexHtml });
  });

  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(port, "127.0.0.1", () => {
      server.off("error", reject);
      resolve();
    });
  });

  const address = server.address();
  if (!address || typeof address === "string") {
    throw new Error("Renderer server did not bind to a TCP port.");
  }

  return {
    port: address.port,
    url: rendererIndexUrl(address.port),
    close: () => closeServer(server),
  };
}

async function serveRendererRequest({ request, response, distRoot, desktopIndexHtml }) {
  const filePath = resolveRendererFilePath({
    requestUrl: request.url ?? "/",
    method: request.method,
    acceptHeader: request.headers.accept,
    distRoot,
  });
  if (!filePath) {
    respondNotFound(response);
    return;
  }
  if (
    typeof desktopIndexHtml === "string" &&
    path.basename(filePath) === "desktop-index.html" &&
    isPathInsideAllowedRoots(filePath, [distRoot])
  ) {
    respondHtml(response, desktopIndexHtml);
    return;
  }

  try {
    const stat = await fsp.stat(filePath);
    if (!stat.isFile()) {
      respondNotFound(response);
      return;
    }
    response.writeHead(200, {
      "Content-Type": contentTypeForPath(filePath),
      "Content-Length": stat.size,
      "Cache-Control": "no-store",
    });
    fs.createReadStream(filePath).pipe(response);
  } catch (error) {
    if (error?.code !== "ENOENT") {
      response.writeHead(500, { "Content-Type": "text/plain; charset=utf-8" });
      response.end("Internal server error");
      return;
    }
    respondNotFound(response);
  }
}

function resolveRendererFilePath({ requestUrl, method, acceptHeader, distRoot }) {
  const rawPathname = requestUrl.split(/[?#]/, 1)[0] || "/";
  let decodedRawPathname;
  try {
    decodedRawPathname = decodeURIComponent(rawPathname);
  } catch {
    return undefined;
  }
  if (decodedRawPathname.split("/").includes("..")) {
    return undefined;
  }

  let pathname;
  try {
    pathname = new URL(requestUrl, "http://127.0.0.1").pathname;
  } catch {
    return undefined;
  }

  let decodedPathname;
  try {
    decodedPathname = decodeURIComponent(pathname);
  } catch {
    return undefined;
  }

  const normalizedPathname =
    decodedPathname === "/" || isSpaNavigationRequest({ pathname: decodedPathname, method, acceptHeader })
      ? "/desktop-index.html"
      : decodedPathname;
  const relativePath = normalizedPathname.replace(/^\/+/, "");
  const filePath = path.resolve(distRoot, relativePath);
  if (!isPathInsideAllowedRoots(filePath, [distRoot])) {
    return undefined;
  }
  return filePath;
}

function isSpaNavigationRequest({ pathname, method, acceptHeader }) {
  if (method !== "GET" && method !== "HEAD") {
    return false;
  }
  if (!acceptsHtml(acceptHeader)) {
    return false;
  }
  return path.posix.extname(pathname) === "";
}

function acceptsHtml(acceptHeader) {
  if (typeof acceptHeader !== "string") {
    return false;
  }
  return acceptHeader
    .split(",")
    .map((entry) => entry.split(";", 1)[0].trim().toLowerCase())
    .some((mediaType) => mediaType === "text/html" || mediaType === "application/xhtml+xml");
}

function contentTypeForPath(filePath) {
  switch (path.extname(filePath).toLowerCase()) {
    case ".html":
      return "text/html; charset=utf-8";
    case ".js":
    case ".mjs":
      return "text/javascript; charset=utf-8";
    case ".css":
      return "text/css; charset=utf-8";
    case ".json":
      return "application/json; charset=utf-8";
    case ".svg":
      return "image/svg+xml";
    case ".png":
      return "image/png";
    case ".jpg":
    case ".jpeg":
      return "image/jpeg";
    case ".webp":
      return "image/webp";
    case ".woff":
      return "font/woff";
    case ".woff2":
      return "font/woff2";
    default:
      return "application/octet-stream";
  }
}

function respondNotFound(response) {
  response.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
  response.end("Not found");
}

function respondHtml(response, html) {
  response.writeHead(200, {
    "Content-Type": "text/html; charset=utf-8",
    "Content-Length": Buffer.byteLength(html),
    "Cache-Control": "no-store",
  });
  response.end(html);
}

function closeServer(server) {
  return new Promise((resolve, reject) => {
    server.close((error) => {
      if (error) {
        reject(error);
        return;
      }
      resolve();
    });
    server.closeAllConnections?.();
  });
}

function canListen(port, host) {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once("error", (error) => {
      if (error.code === "EADDRINUSE" || error.code === "EACCES") {
        resolve(false);
        return;
      }
      reject(error);
    });
    server.once("listening", () => {
      server.close(() => resolve(true));
    });
    server.listen(port, host);
  });
}

function delay(ms) {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}
