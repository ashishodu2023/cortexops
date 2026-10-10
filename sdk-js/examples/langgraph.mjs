// LangGraph.js: trace every graph node and tool call.
// Runs offline (no LLM): npm install @cortexops/sdk @langchain/langgraph @langchain/core zod
import { AIMessage } from "@langchain/core/messages";
import { tool } from "@langchain/core/tools";
import { END, MessagesAnnotation, START, StateGraph } from "@langchain/langgraph";
import { ToolNode } from "@langchain/langgraph/prebuilt";
import { CortexTracer, wrapLangGraph } from "@cortexops/sdk";
import { z } from "zod";

const lookupRefund = tool(async ({ refund_id }) => JSON.stringify({ refund_id, status: "approved" }), {
  name: "lookup_refund",
  description: "Look up the status of a refund",
  schema: z.object({ refund_id: z.string() }),
});

// Stand-in for an LLM node: asks for the tool once, then answers from its result.
function agent(state) {
  const last = state.messages.at(-1);
  if (last?.getType() === "tool") {
    return { messages: [new AIMessage(`Refund status: ${JSON.parse(last.content).status}`)] };
  }
  return {
    messages: [new AIMessage({ content: "", tool_calls: [{ id: "call_1", name: "lookup_refund", args: { refund_id: "REF-8821" } }] })],
  };
}

const graph = new StateGraph(MessagesAnnotation)
  .addNode("agent", agent)
  .addNode("tools", new ToolNode([lookupRefund]))
  .addEdge(START, "agent")
  .addConditionalEdges("agent", (s) => (s.messages.at(-1).tool_calls?.length ? "tools" : END))
  .addEdge("tools", "agent")
  .compile();

// Without CORTEXOPS_API_KEY traces stay in memory (tracer.lastTrace()).
const tracer = new CortexTracer({ project: "refund-graph" });
const traced = wrapLangGraph(tracer, graph); // or tracer.wrap(graph)

const result = await traced.invoke({ messages: [{ role: "user", content: "Where is refund REF-8821?" }] });
console.log(result.messages.at(-1).content);

const trace = tracer.lastTrace();
for (const node of trace.nodes) {
  console.log(`  ${node.node_name}: ${node.tool_calls.map((c) => `${c.name} (${c.status})`).join(", ") || "-"}`);
}
await tracer.shutdown();
