import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { ConfigPage } from "@/components/ConfigPage";

function setFetch(body: unknown, status = 200) {
  global.fetch = vi.fn(async () => {
    const text = JSON.stringify(body);
    return {
      ok: status >= 200 && status < 300,
      status,
      text: async () => text,
      json: async () => body,
    } as Response;
  }) as unknown as typeof fetch;
}

beforeEach(() => {
  global.fetch = vi.fn(async () => ({ ok: true, status: 200, text: async () => "{}", json: async () => ({}) } as Response)) as unknown as typeof fetch;
});

function pickFile(yaml: string): File {
  return new File([yaml], "scenario.yaml", { type: "text/yaml" });
}

describe("ConfigPage validate flow", () => {
  it("shows a passing result when the backend returns valid=true", async () => {
    setFetch({
      code: 0,
      data: { valid: true, resolved_config_hash: "abc123", warnings: [], errors: [] },
      message: "ok",
    });
    render(<ConfigPage />);
    const input = screen.getByTestId("config-file-input") as HTMLInputElement;
    fireEvent.change(input, { target: { files: [pickFile("scenario:\n  site:\n    coordinate_system: ENU\n")] } });
    await waitFor(() => expect(screen.getByTestId("config-result")).toBeTruthy());
    expect(screen.getByTestId("config-result").textContent).toContain("通过");
    expect(screen.getByTestId("config-result").textContent).toContain("abc123");
  });

  it("shows errors when the backend returns valid=false", async () => {
    setFetch({
      code: 0,
      data: {
        valid: false,
        resolved_config_hash: null,
        warnings: [],
        errors: [{ schema_version: "1.0", code: "CFG_E_BOUNDARY", message: "bad boundary", details: {} }],
      },
      message: "ok",
    });
    render(<ConfigPage />);
    fireEvent.change(screen.getByTestId("config-file-input"), {
      target: { files: [pickFile("scenario:\n  site: {}\n")] },
    });
    await waitFor(() => expect(screen.getByTestId("config-result")).toBeTruthy());
    expect(screen.getByTestId("config-result").textContent).toContain("未通过");
    expect(screen.getByTestId("config-result").textContent).toContain("CFG_E_BOUNDARY");
  });

  it("surfaces a backend M_E_* error code on failure", async () => {
    setFetch({ code: "M_E_CONFIG_INVALID", data: null, message: "malformed", details: {} }, 422);
    render(<ConfigPage />);
    fireEvent.change(screen.getByTestId("config-file-input"), {
      target: { files: [pickFile("scenario:\n  site: {}\n")] },
    });
    await waitFor(() => expect(screen.getByTestId("config-error")).toBeTruthy());
    expect(screen.getByTestId("config-error").textContent).toContain("M_E_CONFIG_INVALID");
  });
});
