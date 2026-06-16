export interface DesktopRuntimeConfig {
  apiBase?: string;
  wsBase?: string;
  backendPort?: number;
  mode?: "browser" | "desktop";
}

export function getRuntimeConfig(): Required<Pick<DesktopRuntimeConfig, "mode">> & DesktopRuntimeConfig {
  const injected = typeof window !== "undefined" ? window.__MULTI_CRANE_DESKTOP__ : undefined;
  const params = typeof window !== "undefined" ? new URLSearchParams(window.location.search) : new URLSearchParams();
  const queryApiBase = params.get("desktopApiBase") ?? undefined;
  const queryWsBase = params.get("desktopWsBase") ?? undefined;
  const queryPort = params.get("desktopBackendPort");
  return {
    mode: injected?.mode ?? (queryApiBase ? "desktop" : "browser"),
    apiBase: injected?.apiBase ?? queryApiBase,
    wsBase: injected?.wsBase ?? queryWsBase,
    backendPort: injected?.backendPort ?? (queryPort ? Number(queryPort) : undefined),
  };
}

export function getApiBase(): string {
  return getRuntimeConfig().apiBase ?? "/api";
}

export function getWsBase(): string {
  return getRuntimeConfig().wsBase ?? "/ws";
}
