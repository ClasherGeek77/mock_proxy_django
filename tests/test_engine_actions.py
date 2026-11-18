import json
import os
import time

import pytest
import requests


def test_response_override_answers_synthetically(api, make_rule):
    rule = make_rule(
        responseOverride={
            "status": 418,
            "headersReplace": {"X-Mock": "1"},
            "bodySet": {"teapot": True},
        }
    )
    res = api.get(rule.path)
    assert res.status_code == 418
    assert res.headers["X-Mock"] == "1"
    assert res.headers["Content-Type"] == "application/json"
    assert res.json() == {"teapot": True}


def test_string_body_is_sent_verbatim(api, make_rule):
    rule = make_rule(responseOverride={"status": 200, "bodySet": "plain words"})
    assert api.get(rule.path).text == "plain words"


def test_delay_is_a_floor_on_the_response_time(api, make_rule):
    rule = make_rule(delayMs=400, responseOverride={"status": 200, "bodySet": {}})
    start = time.perf_counter()
    res = api.get(rule.path)
    assert res.status_code == 200
    assert time.perf_counter() - start >= 0.4


def test_delay_is_applied_once_not_per_phase(api, make_rule):
    rule = make_rule(delayMs=400, responseOverride={"status": 200, "bodySet": {}})
    start = time.perf_counter()
    api.get(rule.path)
    assert time.perf_counter() - start < 0.8


def test_disconnect_closes_the_socket_without_a_reply(api, make_rule):
    rule = make_rule(disconnect=True)
    with pytest.raises(requests.exceptions.ConnectionError):
        api.get(rule.path)


def test_request_override_url_rewrites_the_path(api, make_rule, upstream):
    rule = make_rule(proxyTo=upstream, requestOverride={"url": "/rewritten?id=8123"})
    out = api.get(rule.path).json()
    assert out["path"] == "/rewritten?id=8123"


def test_request_override_body_replace_edits_a_json_path(api, make_rule, upstream):
    rule = make_rule(
        match_extra={"method": "POST"},
        proxyTo=upstream,
        requestOverride={"bodyReplace": {"id": "4242"}},
    )
    out = api.post(rule.path, json={"id": "777", "amount": 1}).json()
    assert json.loads(out["body"]) == {"id": "4242", "amount": 1}


def test_request_override_body_set_replaces_the_body(api, make_rule, upstream):
    rule = make_rule(
        match_extra={"method": "POST"},
        proxyTo=upstream,
        requestOverride={"bodySet": {"id": "1500"}},
    )
    out = api.post(rule.path, json={"id": "1"}).json()
    assert json.loads(out["body"]) == {"id": "1500"}


def test_request_override_method_swap(api, make_rule, upstream):
    rule = make_rule(
        proxyTo=upstream,
        requestOverride={"method": "POST", "bodySet": {"id": "8001"}},
    )
    out = api.get(rule.path).json()
    assert out["method"] == "POST"
    assert json.loads(out["body"]) == {"id": "8001"}


def test_proxy_to_replays_the_request_against_the_upstream(api, make_rule, upstream):
    rule = make_rule(
        match_extra={"method": "POST"},
        proxyTo=upstream,
        requestOverride={"headersReplace": {"X-Test": "added"}},
    )
    res = api.post(rule.path + "/x?q=1", data="payload")
    out = res.json()
    assert out["upstream"] is True
    assert out["method"] == "POST"
    assert out["path"] == rule.path + "/x?q=1"
    assert out["body"] == "payload"
    assert out["x-test"] == "added"


def test_proxy_to_a_dead_origin_is_bad_gateway(api, make_rule):
    rule = make_rule(proxyTo="http://127.0.0.1:1")
    assert api.get(rule.path).status_code == 502


def test_proxy_to_refuses_non_http_schemes(api, make_rule):
    rule = make_rule(proxyTo="file:///etc")
    res = api.get(rule.path)
    assert res.status_code == 502
    assert "http(s)" in res.json()["detail"]


def test_lowest_priority_number_wins(api, make_rule):
    loser = make_rule(priority=5, responseOverride={"status": 202})
    winner_doc = {
        "rule-name": "w-" + loser.name,
        "priority": 2,
        "match": {"urlContains": loser.path},
        "responseOverride": {"status": 203},
    }
    api.post("/api/rules", json=winner_doc)
    try:
        assert api.get(loser.path).status_code == 203
    finally:
        api.delete("/api/rules/" + winner_doc["rule-name"])
    assert api.get(loser.path).status_code == 202


def test_inactive_rule_never_fires(api, make_rule):
    rule = make_rule(active=False, responseOverride={"status": 202})
    assert api.get(rule.path).status_code == 404


def test_host_macro_resolves_to_loopback(api, make_rule):
    rule = make_rule(
        responseOverride={"status": 200, "bodySet": {"to": "http://{host}:1/x"}}
    )
    assert api.get(rule.path).json() == {"to": "http://127.0.0.1:1/x"}


def test_response_override_serves_stored_content_by_reference(api, make_rule):
    api.put("/api/rule-content/engine-page.html", data="<h1>stored</h1>")
    rule = make_rule(
        responseOverride={
            "status": 200,
            "bodyHTML": "{host}/rule-content/engine-page.html",
        }
    )
    res = api.get(rule.path)
    assert res.text == "<h1>stored</h1>"
    assert res.headers["Content-Type"].startswith("text/html")


def test_pause_answers_503_everywhere_except_health_and_admin(api, make_rule):
    rule = make_rule(responseOverride={"status": 200})
    assert api.post("/api/mock-state", json={"paused": True}).json() == {"paused": True}
    assert api.get(rule.path).status_code == 503
    assert api.get(rule.path).json() == {"mocking": "paused"}
    assert api.get("/health").status_code == 200
    assert api.get("/api/rules").status_code == 200
    api.post("/api/mock-state", json={"paused": False})
    assert api.get(rule.path).status_code == 200


def test_rules_json_edits_are_picked_up_without_a_restart(api, server_dir):
    if server_dir is None:
        pytest.skip("needs the server's files, MOCK_URL run")
    path = os.path.join(server_dir, "rules.json")
    with open(path, encoding="utf-8") as fh:
        rules = json.load(fh)
    edited = rules + [
        {
            "rule-name": "live-edit",
            "active": True,
            "priority": 1,
            "match": {"urlContains": "/live-edit"},
            "responseOverride": {"status": 201},
        }
    ]
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(edited, fh)
        assert api.get("/live-edit").status_code == 201
    finally:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(rules, fh)
    assert api.get("/live-edit").status_code == 404
