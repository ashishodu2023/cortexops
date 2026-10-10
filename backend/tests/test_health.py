def test_health_reports_release_version(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["version"] == "0.6.0"
