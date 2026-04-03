import pytest


def pytest_collection_modifyitems(config, items):
    skip_backend = pytest.mark.skip(reason="requires backend dependencies")
    for item in items:
        if "TestAlertPayload" in item.nodeid or "TestApiKeyGeneration" in item.nodeid:
            item.add_marker(skip_backend)