/// <reference types="vite/client" />

interface Window {
  __MULTI_CRANE_DESKTOP__?: {
    apiBase?: string;
    wsBase?: string;
    backendPort?: number;
    mode?: "browser" | "desktop";
  };
}
