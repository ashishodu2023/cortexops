"""LLM prompt/response capture on nodes."""

from tests.helpers import make_trace


def test_llm_span():
    trace = make_trace(
        {"output": "approved"},
        llm_prompt="Should we refund REF-1?",
        llm_response="Yes, approve the refund.",
    )
    node = trace.nodes[0]
    assert node.llm_prompt and "refund" in node.llm_prompt
    assert node.llm_response and "approve" in node.llm_response


def test_llm_fields_optional():
    trace = make_trace({"output": "ok"})
    assert trace.nodes[0].llm_prompt is None
