import { describe, it, expect } from "vitest";
import { parseConfigText, scrubSecrets, toValidateRequest, buildValidateRequest } from "@/api/config";

describe("scrubSecrets", () => {
  it("masks api_key / token / secret recursively, keeps the rest", () => {
    const out = scrubSecrets({
      experiment: { api_key: "sk-real", api_key_id: "id", model: "m" },
      scenario: {
        token: "t",
        site: { name: "demo" },
        context_over_tokens: 12000,
        prompt_tokens: 12,
      },
    }) as Record<string, Record<string, unknown>>;
    expect(out.experiment.api_key).toBe("***");
    expect(out.experiment.api_key_id).toBe("***");
    expect(out.experiment.model).toBe("m");
    expect(out.scenario.token).toBe("***");
    expect(out.scenario.context_over_tokens).toBe(12000);
    expect(out.scenario.prompt_tokens).toBe(12);
    expect((out.scenario.site as Record<string, unknown>).name).toBe("demo");
  });

  it("masks api_key_env with other key-like fields", () => {
    const out = scrubSecrets({
      api_key: "sk-real",
      api_key_env: "DEEPSEEK_API_KEY",
    }) as Record<string, unknown>;
    expect(out.api_key).toBe("***");
    expect(out.api_key_env).toBe("***");
  });

  it("walks arrays", () => {
    const out = scrubSecrets([{ token: "x" }, { ok: 1 }]) as Record<string, unknown>[];
    expect(out[0].token).toBe("***");
    expect(out[1].ok).toBe(1);
  });
});

describe("parseConfigText", () => {
  it("parses JSON", () => {
    expect(parseConfigText('{"a":1}')).toEqual({ a: 1 });
  });

  it("falls back to YAML for non-JSON", () => {
    expect(parseConfigText("a: 1\nb: [2, 3]")).toEqual({ a: 1, b: [2, 3] });
  });

  it("throws on empty input", () => {
    expect(() => parseConfigText("   ")).toThrow();
  });
});

describe("toValidateRequest / buildValidateRequest", () => {
  it("splits a combined config and strips runtime key fields", () => {
    const req = toValidateRequest({ scenario: { site: {} }, experiment: { api_key: "k", model: "m" } });
    expect(req.scenario).toEqual({ site: {} });
    expect((req.experiment as Record<string, unknown>).api_key).toBeUndefined();
    expect((req.experiment as Record<string, unknown>).model).toBe("m");
  });

  it("treats a bare object as the scenario", () => {
    const req = toValidateRequest({ site: { boundary: {} } });
    expect(req.scenario).toMatchObject({ site: { boundary: {} } });
    expect(req.experiment).toBeFalsy();
  });

  it("rejects non-object roots", () => {
    expect(() => toValidateRequest([1, 2, 3])).toThrow();
    expect(() => toValidateRequest("hello")).toThrow();
  });

  it("buildValidateRequest parses YAML and strips runtime key fields", () => {
    const req = buildValidateRequest(
      "scenario:\n  site:\n    coordinate_system: ENU\nexperiment:\n  api_key: secret123\n  model: m\n",
    );
    expect((req.scenario as Record<string, unknown>).site).toBeDefined();
    expect((req.experiment as Record<string, unknown>).api_key).toBeUndefined();
    expect((req.experiment as Record<string, unknown>).model).toBe("m");
  });

  it("strips runtime key fields from validation payloads", () => {
    const req = buildValidateRequest(
      [
        "scenario:",
        "  scenario_id: curated",
        "experiment:",
        "  llm:",
        "    provider: deepseek",
        "    model: deepseek-chat",
        "    api_key: sk-real-secret-123456",
        "    api_key_env: DEEPSEEK_API_KEY",
      ].join("\n"),
    );

    const llm = ((req.experiment as Record<string, unknown>).llm ??
      {}) as Record<string, unknown>;
    expect(llm.api_key).toBeUndefined();
    expect(llm.api_key_env).toBeUndefined();
  });
});
