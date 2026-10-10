"""Offline stand-ins for hosted LLMs, used only to verify the integration guides.

Every fake implements the same deterministic policy so the guides' golden dataset passes:
if the user mentions a refund id (REF-1234) and no tool result is available yet, call
`lookup_refund(refund_id=...)`; once a tool result is available, answer with it; otherwise
reply with a greeting. Each fake plugs into the framework's own model interface, so the
framework's real agent loop, tool execution, and result objects are exercised.
"""
from __future__ import annotations

import json
import re
from typing import Any

REF = re.compile(r"REF-\d+")


def _answer(refund_id: str, status: str) -> str:
    return f"Refund {refund_id} is {status}."


GREETING = "Hi! Ask me about a refund by its ID, for example REF-8821."


# ── LangGraph / LangChain ────────────────────────────────────────────────────

def _langchain_model_cls():
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatGeneration, ChatResult

    class FakeChatOpenAI(BaseChatModel):
        model: str = "fake"

        @property
        def _llm_type(self) -> str:
            return "fake-tool-calling"

        def bind_tools(self, tools: Any, **kwargs: Any) -> FakeChatOpenAI:
            return self

        def _generate(self, messages: list[Any], stop: Any = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
            last = messages[-1]
            if last.type == "tool":
                human = next(m.content for m in messages if m.type == "human")
                message = AIMessage(content=_answer(REF.search(human).group(0), str(last.content)))
            else:
                match = REF.search(last.content)
                message = (
                    AIMessage(content="", tool_calls=[{"name": "lookup_refund", "args": {"refund_id": match.group(0)},
                                                       "id": "call_1", "type": "tool_call"}])
                    if match else AIMessage(content=GREETING)
                )
            return ChatResult(generations=[ChatGeneration(message=message)])

    return FakeChatOpenAI


def __getattr__(name: str) -> Any:
    if name == "FakeChatOpenAI":
        return _langchain_model_cls()
    raise AttributeError(name)


# ── PydanticAI ───────────────────────────────────────────────────────────────

def pydantic_ai_model() -> Any:
    from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart, UserPromptPart
    from pydantic_ai.models.function import FunctionModel

    def respond(messages: list[Any], info: Any) -> ModelResponse:
        parts = messages[-1].parts
        returned = [p for p in parts if isinstance(p, ToolReturnPart)]
        if returned:
            prompt = next(p.content for m in messages for p in m.parts if isinstance(p, UserPromptPart))
            return ModelResponse(parts=[TextPart(_answer(REF.search(prompt).group(0), str(returned[0].content)))])
        prompt = " ".join(str(p.content) for p in parts if isinstance(p, UserPromptPart))
        match = REF.search(prompt)
        if match:
            return ModelResponse(parts=[ToolCallPart("lookup_refund", {"refund_id": match.group(0)})])
        return ModelResponse(parts=[TextPart(GREETING)])

    return FunctionModel(respond)


# ── OpenAI Agents SDK ────────────────────────────────────────────────────────

def openai_agents_model() -> Any:
    from agents import ModelResponse, Usage
    from agents.models.interface import Model
    from openai.types.responses import ResponseFunctionToolCall, ResponseOutputMessage, ResponseOutputText

    def message(text: str) -> ResponseOutputMessage:
        return ResponseOutputMessage(
            id="msg_1", type="message", role="assistant", status="completed",
            content=[ResponseOutputText(type="output_text", text=text, annotations=[])],
        )

    class FakeModel(Model):
        async def get_response(self, system_instructions, input, model_settings, tools, output_schema, handoffs,
                               tracing, **kwargs):
            items = [{"content": input, "role": "user"}] if isinstance(input, str) else list(input)
            outputs = [i for i in items if isinstance(i, dict) and i.get("type") == "function_call_output"]
            prompt = next(str(i.get("content")) for i in items if isinstance(i, dict) and i.get("role") == "user")
            match = REF.search(prompt)
            if outputs:
                out = [message(_answer(match.group(0), str(outputs[-1]["output"])))]
            elif match:
                out = [ResponseFunctionToolCall(type="function_call", call_id="call_1", name="lookup_refund",
                                                arguments=json.dumps({"refund_id": match.group(0)}), id="fc_1")]
            else:
                out = [message(GREETING)]
            return ModelResponse(output=out, usage=Usage(), response_id=None)

        def stream_response(self, *args, **kwargs):
            raise NotImplementedError("streaming is not used by the guide")

    return FakeModel()


# ── CrewAI ───────────────────────────────────────────────────────────────────

def crewai_llm() -> Any:
    from crewai import BaseLLM

    class FakeCrewLLM(BaseLLM):
        def call(self, messages, tools=None, callbacks=None, available_functions=None, from_task=None,
                 from_agent=None, response_model=None):
            if isinstance(messages, str):
                messages = [{"role": "user", "content": messages}]
            history = "\n".join(str(m.get("content", "")) for m in messages if m.get("role") != "system")
            match = REF.search(history)
            observation = re.search(r"^Observation:\s*(.+)", history, re.MULTILINE)
            if match and observation:
                answer = _answer(match.group(0), observation.group(1).strip())
                return f"Thought: I now know the final answer\nFinal Answer: {answer}"
            if match:
                return ('Thought: I should look up the refund\nAction: lookup_refund\n'
                        f'Action Input: {{"refund_id": "{match.group(0)}"}}')
            return f"Thought: No refund id was given\nFinal Answer: {GREETING}"

        def supports_function_calling(self) -> bool:
            return False

    return FakeCrewLLM(model="fake-crew-llm")


# ── Google ADK ───────────────────────────────────────────────────────────────

def adk_model() -> Any:
    from google.adk.models import BaseLlm, LlmResponse
    from google.genai import types

    class FakeGemini(BaseLlm):
        async def generate_content_async(self, llm_request, stream: bool = False):
            contents = llm_request.contents
            responses = [p.function_response for c in contents for p in (c.parts or []) if p.function_response]
            prompt = next(p.text for c in contents if c.role == "user" for p in (c.parts or []) if p.text)
            match = REF.search(prompt)
            if responses:
                status = responses[-1].response.get("status", responses[-1].response)
                part = types.Part(text=_answer(match.group(0), str(status)))
            elif match:
                part = types.Part(function_call=types.FunctionCall(name="lookup_refund",
                                                                   args={"refund_id": match.group(0)}))
            else:
                part = types.Part(text=GREETING)
            yield LlmResponse(content=types.Content(role="model", parts=[part]))

    return FakeGemini(model="fake-gemini")
