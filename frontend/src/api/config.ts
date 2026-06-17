// Config upload helpers: parse JSON or YAML, split a combined config into
// scenario/experiment/dataset, and scrub secret-like fields before the payload
// leaves the browser. The backend is still the authority for validation; this
// only feeds POST /scenarios/validate and never starts a run.

import yaml from "js-yaml";
import type { EpisodeStartRequest, ScenarioValidateRequest } from "@/types/api";

const SECRET_KEY = /(^|[_-])(api[-_]?key|apikey|token|secret|authorization|password)([_-]|$)/i;
const SECRET_ALLOWLIST = new Set(["api_key_env"]);

/** Recursively replace secret-like values with "***". */
export function scrubSecrets(obj: unknown): unknown {
  if (Array.isArray(obj)) return obj.map(scrubSecrets);
  if (obj && typeof obj === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(obj as Record<string, unknown>)) {
      out[k] = SECRET_ALLOWLIST.has(k) ? scrubSecrets(v) : SECRET_KEY.test(k) ? "***" : scrubSecrets(v);
    }
    return out;
  }
  return obj;
}

/** Parse a config file body as JSON, falling back to YAML. */
export function parseConfigText(text: string): unknown {
  const trimmed = text.trim();
  if (!trimmed) throw new Error("空配置");
  try {
    return JSON.parse(trimmed);
  } catch {
    // not JSON -> try YAML
  }
  return yaml.load(trimmed);
}

/**
 * Turn one or more parsed config documents into a ScenarioValidateRequest.
 * - If the object has a top-level `scenario` key, treat it as a combined config.
 * - Otherwise treat the whole object as the scenario.
 * Secrets are scrubbed before return.
 */
export function toValidateRequest(parsed: unknown): ScenarioValidateRequest {
  if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
    const rec = parsed as Record<string, unknown>;
    if (rec.scenario !== undefined || rec.experiment !== undefined || rec.dataset !== undefined) {
      return {
        scenario: rec.scenario != null ? (scrubSecrets(rec.scenario) as Record<string, unknown>) : null,
        experiment: rec.experiment != null ? (scrubSecrets(rec.experiment) as Record<string, unknown>) : null,
        dataset: rec.dataset != null ? (scrubSecrets(rec.dataset) as Record<string, unknown>) : null,
        overrides: scrubSecrets(rec.overrides ?? {}) as Record<string, unknown>,
      };
    }
    return { scenario: scrubSecrets(rec) as Record<string, unknown> };
  }
  throw new Error("配置根必须是对象");
}

export function buildValidateRequest(text: string): ScenarioValidateRequest {
  return toValidateRequest(scrubSecrets(parseConfigText(text)));
}

export function toStartRequest(parsed: unknown): EpisodeStartRequest {
  if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
    const rec = parsed as Record<string, unknown>;
    if (rec.scenario !== undefined || rec.experiment !== undefined || rec.dataset !== undefined) {
      return {
        scenario: rec.scenario != null ? (rec.scenario as Record<string, unknown>) : null,
        experiment: rec.experiment != null ? (rec.experiment as Record<string, unknown>) : null,
        dataset: rec.dataset != null ? (rec.dataset as Record<string, unknown>) : null,
        overrides: (rec.overrides ?? {}) as Record<string, unknown>,
      };
    }
    return { scenario: rec };
  }
  throw new Error("config root must be an object");
}

export function buildStartRequest(text: string): EpisodeStartRequest {
  return toStartRequest(parseConfigText(text));
}
