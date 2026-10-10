const MAX_DEPTH = 32;

export function isPlainObject(value: unknown): value is Record<string, unknown> {
  if (value === null || typeof value !== "object") return false;
  const proto = Object.getPrototypeOf(value);
  return proto === Object.prototype || proto === null;
}

export function isPromiseLike<T = unknown>(value: unknown): value is PromiseLike<T> {
  return (
    value !== null &&
    (typeof value === "object" || typeof value === "function") &&
    typeof (value as { then?: unknown }).then === "function"
  );
}

/**
 * Convert an arbitrary value into something `JSON.stringify` can always serialize:
 * cycles, BigInt, functions, Errors, Maps/Sets and class instances are all handled.
 */
export function toJsonSafe(value: unknown): unknown {
  return convert(value, 0, new Set<object>());
}

function convert(value: unknown, depth: number, ancestors: Set<object>): unknown {
  if (value === null) return null;
  switch (typeof value) {
    case "string":
    case "boolean":
      return value;
    case "number":
      return Number.isFinite(value) ? value : null;
    case "bigint":
      return value.toString();
    case "undefined":
    case "function":
    case "symbol":
      return undefined;
  }
  const obj = value as object;
  if (ancestors.has(obj)) return "[Circular]";
  if (depth >= MAX_DEPTH) return "[MaxDepth]";
  if (obj instanceof Date) return Number.isNaN(obj.getTime()) ? null : obj.toISOString();
  if (obj instanceof Error) return { name: obj.name, message: obj.message };
  if (ArrayBuffer.isView(obj) || obj instanceof ArrayBuffer) {
    return `[binary ${(obj as ArrayBuffer).byteLength} bytes]`;
  }
  ancestors.add(obj);
  try {
    const toJSON = (obj as { toJSON?: unknown }).toJSON;
    if (typeof toJSON === "function") {
      return convert(toJSON.call(obj), depth + 1, ancestors);
    }
    if (Array.isArray(obj)) {
      return obj.map((item) => {
        const v = convert(item, depth + 1, ancestors);
        return v === undefined ? null : v;
      });
    }
    if (obj instanceof Map) {
      const out: Record<string, unknown> = {};
      for (const [k, v] of obj) {
        const converted = convert(v, depth + 1, ancestors);
        if (converted !== undefined) out[String(k)] = converted;
      }
      return out;
    }
    if (obj instanceof Set) {
      return [...obj].map((item) => {
        const v = convert(item, depth + 1, ancestors);
        return v === undefined ? null : v;
      });
    }
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(obj)) {
      const converted = convert(v, depth + 1, ancestors);
      if (converted !== undefined) out[k] = converted;
    }
    return out;
  } catch {
    return "[Unserializable]";
  } finally {
    ancestors.delete(obj);
  }
}

/** JSON-safe record: objects pass through (sanitized), anything else is wrapped under `key`. */
export function toRecord(value: unknown, key = "result"): Record<string, unknown> {
  if (value !== null && typeof value === "object" && !Array.isArray(value)) {
    const safe = toJsonSafe(value);
    if (safe !== null && typeof safe === "object" && !Array.isArray(safe)) {
      return safe as Record<string, unknown>;
    }
    return { [key]: safe };
  }
  const safe = toJsonSafe(value);
  return safe === undefined ? {} : { [key]: safe };
}

/** Normalize call arguments into a trace `input` record. */
export function argsToInput(args: readonly unknown[]): Record<string, unknown> {
  if (args.length === 0) return {};
  if (args.length === 1) {
    const [only] = args;
    if (isPlainObject(only)) return toRecord(only);
    return { input: toJsonSafe(only) ?? null };
  }
  return { args: toJsonSafe(args) as unknown[] };
}

/** Parse a JSON string into an object when possible (tool-call arguments are often strings). */
export function parseArgs(value: unknown): Record<string, unknown> {
  if (typeof value === "string") {
    try {
      const parsed: unknown = JSON.parse(value);
      return toRecord(parsed, "input");
    } catch {
      return value === "" ? {} : { input: value };
    }
  }
  if (value === undefined || value === null) return {};
  return toRecord(value, "input");
}

export function errorMessage(err: unknown): string {
  if (err instanceof Error) return err.message;
  if (typeof err === "string") return err;
  try {
    return String(err);
  } catch {
    return "unknown error";
  }
}
