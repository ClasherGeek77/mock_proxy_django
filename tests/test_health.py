def test_health_is_ok(api):
    res = api.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_version_names_the_app(api):
    res = api.get("/api/version")
    assert res.status_code == 200
    assert res.json()["name"] == "mock_proxy_django"


def test_ui_is_served_as_html(api):
    res = api.get("/ui")
    assert res.status_code == 200
    assert res.headers["Content-Type"].startswith("text/html")
    assert "<title>mock proxy" in res.text


def test_unknown_path_is_not_found(api):
    res = api.get("/nothing/here/at/all")
    assert res.status_code == 404
    assert res.json() == {"error": "not found"}


def test_cors_is_wide_open(api):
    res = api.options("/api/rules")
    assert res.status_code == 204
    assert res.headers["Access-Control-Allow-Origin"] == "*"
