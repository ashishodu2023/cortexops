// Mastra: trace agent.generate() and agent.stream().
// npm install @cortexops/sdk @mastra/core @ai-sdk/openai zod; export OPENAI_API_KEY=... CORTEXOPS_API_KEY=...
import { openai } from "@ai-sdk/openai";
import { Agent } from "@mastra/core/agent";
import { createTool } from "@mastra/core/tools";
import { CortexTracer, wrapMastraAgent } from "@cortexops/sdk";
import { z } from "zod";

const lookupOrder = createTool({
  id: "lookupOrder",
  description: "Look up an order by id",
  inputSchema: z.object({ orderId: z.string() }),
  execute: async ({ orderId }) => ({ orderId, status: "shipped" }),
});

const agent = new Agent({
  name: "support",
  instructions: "Answer order questions using the lookupOrder tool.",
  model: openai("gpt-4o-mini"),
  tools: { lookupOrder },
});

const tracer = new CortexTracer({ project: "support-bot" });
const traced = wrapMastraAgent(tracer, agent); // or tracer.wrap(agent)

const result = await traced.generate("Where is order 42?", { maxSteps: 3 });
console.log(result.text);

const stream = await traced.stream("And order 7?", { maxSteps: 3 });
for await (const delta of stream.textStream) process.stdout.write(delta);
console.log();

await tracer.shutdown();
