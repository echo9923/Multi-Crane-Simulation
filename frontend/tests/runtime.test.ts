import { beforeEach, describe, expect, it } from "vitest";
import { getApiBase, getRuntimeConfig, getWsBase } from "@/runtime";

beforeEach(() => {
  window.history.replaceState(null, "", "/");
  delete window.__MULTI_CRANE_DESKTOP__;
});

describe("runtime config", () => {
  it("defaults to browser-relative API and WS bases", () => {
    expect(getRuntimeConfig()).toEqual({ mode: "browser", apiBase: undefined, wsBase: undefined, backendPort: undefined });
    expect(getApiBase()).toBe("/api");
    expect(getWsBase()).toBe("/ws");
  });

  it("uses desktop-injected runtime config", () => {
    window.__MULTI_CRANE_DESKTOP__ = {
      apiBase: "http://127.0.0.1:8765",
      wsBase: "ws://127.0.0.1:8765/ws",
      backendPort: 8765,
      mode: "desktop",
    };

    expect(getRuntimeConfig()).toEqual({
      apiBase: "http://127.0.0.1:8765",
      wsBase: "ws://127.0.0.1:8765/ws",
      backendPort: 8765,
      mode: "desktop",
    });
    expect(getApiBase()).toBe("http://127.0.0.1:8765");
    expect(getWsBase()).toBe("ws://127.0.0.1:8765/ws");
  });

  it("uses Electron dev query parameters when preload cannot edit Vite HTML", () => {
    window.history.replaceState(
      null,
      "",
      "/?desktopApiBase=http%3A%2F%2F127.0.0.1%3A9000&desktopWsBase=ws%3A%2F%2F127.0.0.1%3A9000%2Fws&desktopBackendPort=9000",
    );

    expect(getRuntimeConfig()).toEqual({
      apiBase: "http://127.0.0.1:9000",
      wsBase: "ws://127.0.0.1:9000/ws",
      backendPort: 9000,
      mode: "desktop",
    });
    expect(getApiBase()).toBe("http://127.0.0.1:9000");
    expect(getWsBase()).toBe("ws://127.0.0.1:9000/ws");
  });
});
