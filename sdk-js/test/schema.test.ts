import { readFileSync } from "node:fs";
import { join } from "node:path";
import { Ajv2020 } from "ajv/dist/2020.js";
import { describe, expect, it } from "vitest";
import { parseDataset, parseDatasetText } from "../src/eval.js";
import { FIXTURES, GOLDEN_YAML } from "./helpers.js";

const schema = JSON.parse(readFileSync(join(FIXTURES, "..", "..", "schema", "golden-dataset.v1.schema.json"), "utf8"));
const validate = new Ajv2020({ allErrors: true }).compile(schema);

describe("golden dataset JSON Schema (v1)", () => {
  it("accepts the repository golden dataset, which both SDKs parse", async () => {
    const raw = await parseDatasetText(readFileSync(GOLDEN_YAML, "utf8"));
    expect(validate(raw), JSON.stringify(validate.errors)).toBe(true);
    expect(parseDataset(raw).cases).toHaveLength(9);
  });

  it("accepts every optional field and rejects malformed cases", () => {
    const full = {
      version: 2,
      project: "p",
      name: "golden",
      description: "d",
      cases: [
        { id: 1, input: { q: "x" }, expected_tool_calls: ["a"], expected_output_contains: ["b"], expected_output_not_contains: ["c"], max_latency_ms: 50, judge: "llm", judge_criteria: "polite", tags: ["t"] },
        { id: "s", input: "plain", max_latency_ms: null },
      ],
    };
    expect(validate(full), JSON.stringify(validate.errors)).toBe(true);
    expect(parseDataset(full).cases.map((c) => c.id)).toEqual(["1", "s"]);

    for (const bad of [
      { cases: [{ id: "x" }] },
      { cases: [{ input: "x" }] },
      { cases: [{ id: "x", input: 3 }] },
      { cases: [{ id: "x", input: "y", expected_tool_calls: "lookup" }] },
      { version: "1.0", cases: [] },
      {},
    ]) {
      expect(validate(bad), JSON.stringify(bad)).toBe(false);
      if (Array.isArray((bad as any).cases) || "version" in bad) expect(() => parseDataset(bad)).toThrow();
    }
  });
});
