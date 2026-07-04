"""Credential save/load/clear."""

from cortexops.auth import save_credentials, load_credentials, clear_credentials


def test_save_load_clear(tmp_path, monkeypatch):
    cred_dir = tmp_path / ".cortexops"
    cred_file = cred_dir / "credentials"
    monkeypatch.setattr("cortexops.auth._CREDENTIALS_DIR", cred_dir)
    monkeypatch.setattr("cortexops.auth._CREDENTIALS_FILE", cred_file)

    save_credentials("cxo-testkey", "payments-agent")
    creds = load_credentials()
    assert creds["api_key"] == "cxo-testkey"
    assert creds["project"] == "payments-agent"
    clear_credentials()
    assert load_credentials() is None
