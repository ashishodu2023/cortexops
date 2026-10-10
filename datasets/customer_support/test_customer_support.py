"""pytest eval gate for the customer_support golden dataset.

    pip install "cortexops[pytest]"
    pytest datasets/customer_support -v

The gate fails the test when any condition is true; swap build_agent() for your own agent.
"""
import cortexops
from support_agent import build_agent


@cortexops.eval_gate("golden.yaml", fail_on=["pass_rate < 1.0", "task_completion < 1.0", "tool_accuracy < 1.0"])
def test_customer_support_reference_agent():
    return build_agent()
