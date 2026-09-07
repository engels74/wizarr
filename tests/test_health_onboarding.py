"""Container liveness must work before the first administrator is configured."""


def test_health_is_json_before_onboarding(app, client, session, monkeypatch):
    monkeypatch.setitem(app.config, "TESTING", False)
    response = client.get("/health", follow_redirects=False)
    assert response.status_code == 200
    assert response.json == {"status": "ok"}
    for path in ["/", "/health-other"]:
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 302
        assert "/setup" in response.headers["Location"]
