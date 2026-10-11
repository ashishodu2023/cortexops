import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

export const DEFAULT_API_URL = "https://api.getcortexops.com";
export const ENV_KEY = "CORTEXOPS_API_KEY";
export const ENV_URL = "CORTEXOPS_API_URL";
export const ENV_PROJECT = "CORTEXOPS_PROJECT";
export const ENV_ENVIRONMENT = "CORTEXOPS_ENVIRONMENT";
export const ENV_SAMPLE_RATE = "CORTEXOPS_SAMPLE_RATE";

function env(name: string): string | undefined {
  const value = typeof process !== "undefined" ? process.env[name] : undefined;
  return value ? value : undefined;
}

/** Path of the credentials file written by the Python CLI (`cortexops login`). */
export function credentialsPath(): string {
  return join(homedir(), ".cortexops", "credentials");
}

export interface StoredCredentials {
  api_key?: string;
  project?: string;
  api_url?: string;
}

export function readCredentials(): StoredCredentials | undefined {
  try {
    const parsed: unknown = JSON.parse(readFileSync(credentialsPath(), "utf8"));
    return parsed && typeof parsed === "object" ? (parsed as StoredCredentials) : undefined;
  } catch {
    return undefined;
  }
}

/** API key: explicit argument > CORTEXOPS_API_KEY > ~/.cortexops/credentials > undefined (local-only). */
export function resolveApiKey(explicit?: string | null): string | undefined {
  if (explicit) return explicit;
  const fromEnv = env(ENV_KEY);
  if (fromEnv) return fromEnv;
  const stored = readCredentials()?.api_key;
  return typeof stored === "string" && stored ? stored : undefined;
}

/** API URL: explicit argument > CORTEXOPS_API_URL > https://api.getcortexops.com (trailing slash stripped). */
export function resolveApiUrl(explicit?: string | null): string {
  return (explicit || env(ENV_URL) || DEFAULT_API_URL).replace(/\/+$/, "");
}

export function resolveProject(explicit?: string | null): string {
  return explicit || env(ENV_PROJECT) || "default";
}

export function resolveEnvironment(explicit?: string | null): string {
  return explicit || env(ENV_ENVIRONMENT) || "development";
}

const NUMBER_RE = /^\s*[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?\s*$/;

/** Sample rate: explicit argument > CORTEXOPS_SAMPLE_RATE > 1.0. Throws on values outside [0, 1]. */
export function resolveSampleRate(explicit?: number | null): number {
  let rate: number;
  if (explicit !== undefined && explicit !== null) {
    rate = explicit;
  } else {
    const raw = env(ENV_SAMPLE_RATE);
    if (raw !== undefined) {
      if (!NUMBER_RE.test(raw)) {
        throw new RangeError(`${ENV_SAMPLE_RATE} must be a number between 0.0 and 1.0, got '${raw}'`);
      }
      rate = Number(raw);
    } else {
      rate = 1.0;
    }
  }
  if (typeof rate !== "number" || Number.isNaN(rate) || rate < 0 || rate > 1) {
    throw new RangeError(`sampleRate must be between 0.0 and 1.0, got ${rate}`);
  }
  return rate;
}
