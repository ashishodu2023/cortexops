"""Client retry-friendly error surface."""

import pytest
from unittest.mock import patch

from cortexops.client import CortexClient


def test_post_raises_on_http_error():
    client = CortexClient(api_key="cxo-x", base_url="https://api.getcortexops.com")

    class FakeResp:
        def raise_for_status(self):
            raise RuntimeError("503")

        def json(self):
            return {}

    with patch("httpx.post", return_value=FakeResp()):
        with pytest.raises(RuntimeError):
            client._post("/v1/traces", {"x": 1})
