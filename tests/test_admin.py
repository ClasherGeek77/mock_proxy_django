import uuid

import pytest

DOC = {
    "priority": 3,
    "match": {"urlContains": "/never-hit"},
    "responseOverride": {"status": 200},
}


@pytest.fixture
def name(api):
    n = "adm-" + uuid.uuid4().hex[:8]
    yield n
    api.delete("/api/rules/" + n)


def test_save_creates_then_updates(api, name):
    first = api.put("/api/rules/" + name, json=DOC)
    assert first.status_code == 201
    assert first.json()["success"] is True
    second = api.put("/api/rules/" + name, json=dict(DOC, priority=4))
    assert second.status_code == 200
    assert api.get("/api/rules/" + name).json()["priority"] == 4


def test_json_suffix_in_the_name_is_stripped(api, name):
    res = api.post("/api/rules", json=dict(DOC, **{"rule-name": name + ".json"}))
    assert res.json()["name"] == name
    assert api.get("/api/rules/" + name).status_code == 200


def test_get_unknown_rule_is_not_found(api):
    assert api.get("/api/rules/no-such-rule-xyz").status_code == 404


@pytest.mark.parametrize(
    "doc, fragment",
    [
        ({"match": {"a": 1}}, "rule-name is required"),
        ({"rule-name": "export"}, "not be one of"),
        ({"rule-name": "bad name!"}, "rule-name must match"),
        ({"rule-name": "ok", "priority": "high"}, "priority must be an integer"),
        ({"rule-name": "ok", "match": []}, "match must be an object"),
    ],
)
def test_invalid_rules_are_rejected(api, doc, fragment):
    res = api.post("/api/rules", json=doc)
    assert res.status_code == 400
    assert fragment in " ".join(res.json()["errors"])


def test_broken_json_is_bad_request(api):
    res = api.post(
        "/api/rules", data="{nope", headers={"Content-Type": "application/json"}
    )
    assert res.status_code == 400


def test_warnings_are_reported_but_the_save_goes_through(api, name):
    res = api.put("/api/rules/" + name, json={"match": {}})
    assert res.status_code == 201
    assert any("never fire" in w for w in res.json()["warnings"])


def test_strict_turns_warnings_into_errors(api, name):
    res = api.put("/api/rules/" + name + "?strict=1", json={"match": {}})
    assert res.status_code == 400
    assert api.get("/api/rules/" + name).status_code == 404


def test_delete_is_soft_and_hides_the_rule(api, name):
    api.put("/api/rules/" + name, json=DOC)
    assert api.delete("/api/rules/" + name).status_code == 200
    assert api.get("/api/rules/" + name).status_code == 404
    assert name not in [r["rule-name"] for r in api.get("/api/rules").json()]
    kept = [
        r
        for r in api.get("/api/rules?includeDeleted=1").json()
        if r["rule-name"] == name
    ]
    assert kept and kept[0]["deletedAt"]


def test_saving_a_deleted_rule_brings_it_back(api, name):
    api.put("/api/rules/" + name, json=DOC)
    api.delete("/api/rules/" + name)
    api.put("/api/rules/" + name, json=DOC)
    assert "deletedAt" not in api.get("/api/rules/" + name).json()


def test_toggle_flips_active(api, name):
    api.put("/api/rules/" + name, json=DOC)
    assert api.post(f"/api/rules/{name}/toggle").json()["active"] is False
    assert api.post(f"/api/rules/{name}/toggle").json()["active"] is True


def test_toggle_unknown_rule_is_not_found(api):
    assert api.post("/api/rules/no-such-rule-xyz/toggle").status_code == 404


def test_export_import_round_trip(api, name):
    api.put("/api/rules/" + name, json=DOC)
    exported = api.get("/api/rules/export").json()
    assert name in [r["rule-name"] for r in exported]
    report = api.post("/api/rules/import", json=exported).json()
    assert report["success"] is True
    assert report["count"] == len(exported)
    assert report["skipped"] == 0


def test_import_reports_partial_failures(api, name):
    good = dict(DOC, **{"rule-name": name})
    report = api.post(
        "/api/rules/import", json=[good, {"nope": 1}, {"rule-name": "test"}]
    ).json()
    assert report["success"] is False
    assert (report["count"], report["skipped"]) == (1, 2)
    assert len(report["errors"]) == 2
    assert api.get("/api/rules/" + name).status_code == 200


def test_import_rejects_a_non_array(api):
    assert api.post("/api/rules/import", json={"rule-name": "x"}).status_code == 400


def test_tester_reports_the_winner_and_all_candidates(api, make_rule):
    rule = make_rule(priority=1, responseOverride={"status": 200})
    out = api.post(
        "/api/rules/test", json={"url": "http://localhost" + rule.path}
    ).json()
    assert out["matched"] is True
    assert out["rule"] == rule.name
    assert out["action"] == "synthetic-response"
    assert out["candidates"] == [rule.name]


def test_tester_names_each_action_type(api, make_rule):
    cases = {
        "disconnect": {"disconnect": True},
        "proxy": {"proxyTo": "http://127.0.0.1:1"},
        "modify-request": {"requestOverride": {"method": "POST"}},
        "delay": {"delayMs": 10},
    }
    for action, doc in cases.items():
        rule = make_rule(**doc)
        out = api.post(
            "/api/rules/test", json={"url": "http://localhost" + rule.path}
        ).json()
        assert out["action"] == action


def test_tester_reports_no_match(api):
    out = api.post(
        "/api/rules/test", json={"url": "http://localhost/zzz-nothing"}
    ).json()
    assert out["matched"] is False
    assert out["action"] == "none"


def test_tester_requires_a_url(api):
    assert api.post("/api/rules/test", json={}).status_code == 400


def test_tester_has_no_side_effects(api, make_rule):
    rule = make_rule(responseOverride={"status": 200})
    api.post("/api/metrics/reset")
    for _ in range(3):
        api.post("/api/rules/test", json={"url": "http://localhost" + rule.path})
    snap = api.get("/api/metrics").json()
    assert snap["total"] == 0
    assert snap["byRule"] == {}


def test_history_keeps_the_previous_version_of_a_save(api, name):
    api.put("/api/rules/" + name, json=dict(DOC, priority=1))
    api.put("/api/rules/" + name, json=dict(DOC, priority=2))
    rows = api.get("/api/history", params={"name": name}).json()
    assert len(rows) == 1
    assert rows[0]["doc"]["priority"] == 1


def test_history_is_capped_at_ten(api, name):
    for prio in range(14):
        api.put("/api/rules/" + name, json=dict(DOC, priority=prio))
    rows = api.get("/api/history", params={"name": name}).json()
    assert len(rows) == 10
    assert rows[0]["doc"]["priority"] == 12  # newest snapshot first


def test_restore_puts_an_old_version_back_and_snapshots_first(api, name):
    api.put("/api/rules/" + name, json=dict(DOC, priority=1))
    api.put("/api/rules/" + name, json=dict(DOC, priority=2))
    old = api.get("/api/history", params={"name": name}).json()[0]
    assert api.post(f"/api/history/{old['id']}/restore").status_code == 200
    assert api.get("/api/rules/" + name).json()["priority"] == 1
    rows = api.get("/api/history", params={"name": name}).json()
    assert (
        rows[0]["doc"]["priority"] == 2
    )  # the version that was replaced is now the newest snapshot


def test_restore_unknown_snapshot_is_not_found(api):
    assert api.post("/api/history/ffffffff/restore").status_code == 404


def test_deleted_rule_can_be_restored_from_history(api, name):
    api.put("/api/rules/" + name, json=DOC)
    api.delete("/api/rules/" + name)
    snap = api.get("/api/history", params={"name": name}).json()[0]
    api.post(f"/api/history/{snap['id']}/restore")
    assert api.get("/api/rules/" + name).status_code == 200


def test_metrics_count_rule_hits_and_statuses(api, make_rule):
    rule = make_rule(responseOverride={"status": 202})
    api.post("/api/metrics/reset")
    api.get(rule.path)
    api.get(rule.path)
    api.get("/zzz-nothing")
    snap = api.get("/api/metrics").json()
    assert snap["byRule"][rule.name]["hits"] == 2
    assert snap["byRule"][rule.name]["actions"] == {"synthetic-response": 2}
    assert snap["total"] == 3
    assert snap["byStatus"] == {"202": 2, "404": 1}
    assert snap["paused"] is False


def test_metrics_reset_zeroes_everything(api, make_rule):
    rule = make_rule(responseOverride={"status": 202})
    api.get(rule.path)
    assert api.post("/api/metrics/reset").json()["success"] is True
    snap = api.get("/api/metrics").json()
    assert (snap["total"], snap["byRule"]) == (0, {})


def test_rule_content_round_trip_and_content_types(api):
    assert api.put("/api/rule-content/adm-page.html", data="<p>x</p>").status_code in (
        200,
        201,
    )
    res = api.get("/rule-content/adm-page.html")
    assert res.text == "<p>x</p>"
    assert res.headers["Content-Type"].startswith("text/html")
    api.put("/api/rule-content/adm-data.json", data='{"k": 1}')
    assert (
        api.get("/rule-content/adm-data.json").headers["Content-Type"]
        == "application/json"
    )
    assert (
        api.get("/rule-content/adm-page").text == "<p>x</p>"
    )  # extension-less name finds the .html
    assert "adm-page.html" in api.get("/api/rule-content").json()
    assert api.delete("/api/rule-content/adm-page.html").status_code == 200
    assert api.get("/rule-content/adm-page.html").status_code == 404
    api.delete("/api/rule-content/adm-data.json")


@pytest.mark.parametrize("bad", ["..%2Fserver.py", ".hidden", "a%2Fb"])
def test_rule_content_names_cannot_escape_the_folder(api, bad):
    assert api.put("/api/rule-content/" + bad, data="x").status_code >= 400
    assert api.get("/rule-content/" + bad).status_code == 404
