// Vercel AI SDK: trace generateText / streamText, or every model call via middleware.
// npm install @cortexops/sdk ai @ai-sdk/openai zod; export OPENAI_API_KEY=... CORTEXOPS_API_KEY=...
import { openai } from "@ai-sdk/openai";
import { generateText, stepCountIs, streamText, tool, wrapLanguageModel } from "ai";
import { CortexTracer, cortexopsMiddleware, wrapGenerateText, wrapStreamText } from "@cortexops/sdk";
import { z } from "zod";

const tracer = new CortexTracer({ project: "support-bot" });

const tools = {
  lookupOrder: tool({
    description: "Look up an order by id",
    inputSchema: z.object({ orderId: z.string() }),
    execute: async ({ orderId }) => ({ orderId, status: "shipped" }),
  }),
};

// 1. Wrap the call: one trace per generateText, a node per step, tool calls with results.
const tracedGenerateText = wrapGenerateText(tracer, generateText);
const { text } = await tracedGenerateText({
  model: openai("gpt-4o-mini"),
  prompt: "Where is order 42?",
  tools,
  stopWhen: stepCountIs(3),
});
console.log(text);

// 2. Streaming: the trace is finalized from onFinish / onError (your callbacks still run).
const tracedStreamText = wrapStreamText(tracer, streamText);
const stream = tracedStreamText({ model: openai("gpt-4o-mini"), prompt: "Say hi in five words." });
for await (const delta of stream.textStream) process.stdout.write(delta);
console.log();

// 3. Middleware: every model call becomes an llm:<model> node on the active trace
//    (here the tracer.wrap() run), or its own trace when called outside one.
const model = wrapLanguageModel({ model: openai("gpt-4o-mini"), middleware: cortexopsMiddleware(tracer) });
const answer = tracer.wrap(async (question) => (await generateText({ model, prompt: question, tools, stopWhen: stepCountIs(3) })).text);
console.log(await answer("Where is order 7?"));

await tracer.shutdown();
