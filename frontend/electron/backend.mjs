import { spawn } from "node:child_process";
import net from "node:net";
import path from "node:path";

export function resolvePythonPath(projectRoot, platform = process.platform) {
  if (platform === "win32") {
    if (projectRoot.includes("\\")) {
      return path.win32.join(projectRoot, ".venv", "Scripts", "python.exe");
    }
    return path.posix.join(projectRoot, ".venv", "Scripts", "python.exe");
  }
  return path.join(projectRoot, ".venv", "bin", "python");
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

export function withRuntimeScript(html, { port }) {
  const tag = runtimeScriptTag({ port });
  if (html.includes("</head>")) {
    return html.replace("</head>", `${tag}</head>`);
  }
  return `${tag}${html}`;
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
