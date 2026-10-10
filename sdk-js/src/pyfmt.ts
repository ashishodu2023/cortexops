/**
 * Helpers that reproduce the Python SDK's string conversions and rounding, so that
 * metric scores and gate messages are identical across the two SDKs.
 */

/** Python `str(value)`. */
export function pyStr(value: unknown): string {
  return typeof value === "string" ? value : pyRepr(value);
}

/** Python `repr(value)` for JSON-like data. */
export function pyRepr(value: unknown, ancestors: Set<object> = new Set()): string {
  if (value === null || value === undefined) return "None";
  if (typeof value === "boolean") return value ? "True" : "False";
  if (typeof value === "number") {
    if (Number.isNaN(value)) return "nan";
    if (!Number.isFinite(value)) return value > 0 ? "inf" : "-inf";
    return String(value);
  }
  if (typeof value === "bigint") return value.toString();
  if (typeof value === "string") return reprString(value);
  if (typeof value === "function" || typeof value === "symbol") return String(value);
  const obj = value as object;
  if (ancestors.has(obj)) return Array.isArray(obj) ? "[...]" : "{...}";
  ancestors.add(obj);
  try {
    if (Array.isArray(obj)) return `[${obj.map((v) => pyRepr(v, ancestors)).join(", ")}]`;
    if (obj instanceof Date) return reprString(obj.toISOString());
    const entries = Object.entries(obj).map(([k, v]) => `${reprString(k)}: ${pyRepr(v, ancestors)}`);
    return `{${entries.join(", ")}}`;
  } finally {
    ancestors.delete(obj);
  }
}

function reprString(s: string): string {
  const quote = s.includes("'") && !s.includes('"') ? '"' : "'";
  let out = "";
  for (const ch of s) {
    if (ch === "\\") out += "\\\\";
    else if (ch === quote) out += `\\${quote}`;
    else if (ch === "\n") out += "\\n";
    else if (ch === "\r") out += "\\r";
    else if (ch === "\t") out += "\\t";
    else out += ch;
  }
  return `${quote}${out}${quote}`;
}

/**
 * Python `round(x, ndigits)`: rounds the exact binary value of `x` (so 76.55, stored as
 * 76.5499999..., rounds down) and breaks exact ties to even.
 */
export function pyRound(x: number, ndigits = 0): number {
  if (!Number.isFinite(x) || Math.abs(x) >= 1e21) return x;
  // toFixed(100) yields the exact decimal expansion of the double for the magnitudes we round
  const [intPart = "0", frac = ""] = Math.abs(x).toFixed(100).split(".");
  const kept = intPart + frac.slice(0, ndigits);
  const rest = frac.slice(ndigits);
  const first = rest[0] ?? "0";
  let roundUp: boolean;
  if (first !== "5") roundUp = first > "5";
  else if (/[1-9]/.test(rest.slice(1))) roundUp = true;
  else roundUp = Number(kept[kept.length - 1]) % 2 === 1;
  const digits = (roundUp ? (BigInt(kept) + 1n).toString() : BigInt(kept).toString()).padStart(ndigits + 1, "0");
  const text = ndigits > 0 ? `${digits.slice(0, -ndigits)}.${digits.slice(-ndigits)}` : digits;
  const result = Number(text);
  return x < 0 ? -result : result;
}

/** Python `str(float(x))`: `0.9 -> "0.9"`, `1 -> "1.0"`. */
export function pyFloat(x: number): string {
  if (Number.isInteger(x) && Math.abs(x) < 1e16) return x.toFixed(1);
  return String(x);
}

/** Python `f"{x:.{digits}f}"`. */
export function fixed(x: number, digits: number): string {
  const text = pyRound(x, digits).toFixed(digits);
  return x < 0 && !text.startsWith("-") ? `-${text}` : text;
}

/** Python `f"{x:.{digits}%}"`. */
export function percent(x: number, digits: number): string {
  return `${fixed(x * 100, digits)}%`;
}
