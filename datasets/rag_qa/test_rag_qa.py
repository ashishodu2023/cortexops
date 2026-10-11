"""pytest eval gate for the rag_qa golden dataset.

    pip install "cortexops[pytest]"
    pytest datasets/rag_qa -v

The gate fails the test when any condition is true; swap build_agent() for your own agent.
"""
import cortexops
from rag_agent import build_agent


@cortexops.eval_gate("golden.yaml", fail_on=["pass_rate < 1.0", "task_completion < 1.0", "tool_accuracy < 1.0"])
def test_rag_qa_reference_agent():
    return build_agent()
