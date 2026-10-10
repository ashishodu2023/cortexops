import { AsyncLocalStorage } from "node:async_hooks";
import type { ToolCall } from "./models.js";

/**
 * While an eval case runs, every tool call recorded by any tracer or integration in the
 * same async context lands here, so `tool_accuracy` sees instrumented calls even when the
 * agent's return value does not self-report `tool_calls_made`.
 */
export interface CaptureSink {
  toolCalls: ToolCall[];
}

const captureStorage = new AsyncLocalStorage<CaptureSink>();

export function withCapture<T>(sink: CaptureSink, fn: () => T): T {
  return captureStorage.run(sink, fn);
}

export function captureToolCall(toolCall: ToolCall): void {
  captureStorage.getStore()?.toolCalls.push(toolCall);
}
