// OpenAI Agents SDK (JS): trace runs, tool calls, handoffs and usage.
// npm install @cortexops/sdk @openai/agents zod; export OPENAI_API_KEY=... CORTEXOPS_API_KEY=...
import { Agent, run, tool } from "@openai/agents";
import { CortexTracer, wrapOpenAIAgent, wrapOpenAIAgentsRun } from "@cortexops/sdk";
import { z } from "zod";

const lookupRefund = tool({
  name: "lookup_refund",
  description: "Look up the status of a refund",
  parameters: z.object({ refund_id: z.string() }),
  execute: async ({ refund_id }) => JSON.stringify({ refund_id, status: "approved" }),
});

const agent = new Agent({
  name: "Refund agent",
  instructions: "Answer refund questions. Always look the refund up first.",
  model: "gpt-4o-mini",
  tools: [lookupRefund],
});

const tracer = new CortexTracer({ project: "refund-agent" });

// Wrap the SDK's run(): works for every agent, including streaming runs.
const tracedRun = wrapOpenAIAgentsRun(tracer, run);
const result = await tracedRun(agent, "What is the status of refund REF-8821?");
console.log(result.finalOutput);

// Or give one agent a traced .run(); this is what tracer.wrap(agent) returns.
const traced = wrapOpenAIAgent(tracer, agent, { run });
const streamed = await traced.run("And refund REF-1234?", { stream: true });
for await (const chunk of streamed.toTextStream()) process.stdout.write(chunk);
console.log();

await tracer.shutdown();
