// JavaScript port of examples/langgraph_payments/agent.py (deterministic mock LLM, no API key).
//
//   npx cortexops-js eval run \
//     --dataset ../examples/langgraph_payments/golden_v1.yaml \
//     --agent ./examples/payments-agent.mjs \
//     --fail-on "task_completion < 0.90"

const MOCK_REFUNDS = {
  "REF-8821": { status: "approved", amount: 49.99, days_remaining: 3 },
  "REF-9902": { status: "pending", amount: 120.0, days_remaining: 7 },
  "REF-1044": { status: "rejected", amount: 19.99, reason: "outside return window" },
};

const MOCK_DISPUTES = {
  duplicate_charge: "billing_error",
  item_not_received: "fulfillment",
  unauthorized: "fraud",
  not_as_described: "product_quality",
};

const ROUTING = {
  fraud: { team: "fraud_prevention", sla_hours: 2, priority: "critical" },
  billing_error: { team: "billing_ops", sla_hours: 24, priority: "high" },
  fulfillment: { team: "fulfillment_ops", sla_hours: 48, priority: "normal" },
  product_quality: { team: "quality_assurance", sla_hours: 72, priority: "normal" },
  general_inquiry: { team: "tier1_support", sla_hours: 96, priority: "low" },
};

export const TOOLS = {
  lookup_refund({ refund_id }) {
    const refund = MOCK_REFUNDS[refund_id];
    if (!refund) return { error: `Refund ${refund_id} not found` };
    return { refund_id, ...refund };
  },
  classify_dispute({ description }) {
    const lower = description.toLowerCase();
    for (const [keyword, category] of Object.entries(MOCK_DISPUTES)) {
      if (lower.includes(keyword.replaceAll("_", " "))) {
        return { category, confidence: 0.92, keyword_matched: keyword };
      }
    }
    return { category: "general_inquiry", confidence: 0.55, keyword_matched: null };
  },
  route_escalation({ category }) {
    const route = ROUTING[category] ?? ROUTING.general_inquiry;
    return { routed_to: route.team, sla_hours: route.sla_hours, priority: route.priority };
  },
};

const DISPUTE_KEYWORDS = ["dispute", "charge", "wrong", "error", "unauthorized", "not received", "delivered", "arrived", "item"];

function decide(state) {
  const lower = state.input.toLowerCase();
  const called = new Set(state.tool_calls_made);
  if (state.input.includes("REF-") && !called.has("lookup_refund")) {
    const match = /REF-\d+/.exec(state.input);
    return { tool: "lookup_refund", args: { refund_id: match ? match[0] : "REF-0000" } };
  }
  if (DISPUTE_KEYWORDS.some((kw) => lower.includes(kw))) {
    if (!called.has("classify_dispute")) return { tool: "classify_dispute", args: { description: state.input } };
    if (!called.has("route_escalation")) {
      const category = state.tool_results.classify_dispute?.category ?? "general_inquiry";
      return { tool: "route_escalation", args: { category } };
    }
  }
  return { tool: null, args: {} };
}

function respond(state) {
  const results = state.tool_results;
  const parts = [];
  if (results.lookup_refund) {
    const r = results.lookup_refund;
    if (r.error) parts.push(r.error);
    else if (r.status === "approved") {
      parts.push(`Refund ${r.refund_id} is approved. Expect credit in ${r.days_remaining} business days.`);
    } else if (r.status === "pending") {
      parts.push(`Refund ${r.refund_id} is pending review (${r.days_remaining} days remaining).`);
    } else {
      parts.push(`Refund ${r.refund_id} was ${r.status}. ${r.reason ?? ""}`);
    }
  }
  if (results.route_escalation) {
    const r = results.route_escalation;
    parts.push(`Your case has been escalated to ${r.routed_to} (SLA: ${r.sla_hours}h, priority: ${r.priority}).`);
  }
  if (!parts.length) parts.push(`Thank you for contacting support regarding: ${state.input}`);
  return parts.join(" ");
}

/**
 * Build the agent. Pass a CortexTracer to record each tool call on the active trace
 * (and on the eval case, so tool_accuracy uses instrumented calls).
 */
export function buildAgent({ tracer } = {}) {
  return {
    async invoke(input) {
      const state = { input: input.input ?? "", tool_calls_made: [], tool_results: {} };
      for (let i = 0; i < 10; i++) {
        const { tool, args } = decide(state);
        if (!tool) break;
        const t0 = performance.now();
        const result = TOOLS[tool](args);
        tracer?.recordToolCall(tool, { args, result, latencyMs: performance.now() - t0 });
        state.tool_calls_made.push(tool);
        state.tool_results[tool] = result;
      }
      return { output: respond(state), tool_calls_made: state.tool_calls_made };
    },
  };
}

export default buildAgent();
