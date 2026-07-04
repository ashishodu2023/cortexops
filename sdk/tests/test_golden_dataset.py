"""GoldenDataset build/load/save."""

from cortexops.dataset import GoldenDataset


def test_golden_dataset_add_and_save(tmp_path):
    ds = GoldenDataset(name="refund-agent-v1")
    ds.add(input="Process refund for order #4821", expected="refund_approved")
    ds.add(input="Cancel subscription", expected="subscription_cancelled")
    path = tmp_path / "refund.yaml"
    ds.save(path)
    loaded = GoldenDataset.load(path)
    assert loaded.name == "refund-agent-v1"
    assert len(loaded.cases) == 2
    assert loaded.cases[0].expected == "refund_approved"
