import csv
import os

import pytest

CSV = os.path.join(os.path.dirname(__file__), "csv_files", "match_matrix.csv")


def rows():
    with open(CSV, newline="", encoding="utf-8") as fh:
        return [pytest.param(r, id=r["case"]) for r in csv.DictReader(fh)]


def header(cell):
    name, _, value = cell.partition(":")
    return {name: value}


@pytest.mark.parametrize("row", rows())
def test_rule_matches_only_when_every_criterion_holds(api, make_rule, row):
    match = {}
    if row["rule_method"]:
        match["method"] = row["rule_method"]
    if row["rule_header"]:
        match["headers"] = header(row["rule_header"])
    if row["rule_body_contains"]:
        match["bodyContains"] = row["rule_body_contains"].split("|")
    rule = make_rule(
        match_extra=match, responseOverride={"status": 299, "bodySet": {"hit": True}}
    )
    if row["rule_path_suffix"]:
        # the urlContains criterion carries the suffix too
        api.put(
            "/api/rules/" + rule.name,
            json={
                "priority": 1,
                "match": dict(match, urlContains=rule.path + row["rule_path_suffix"]),
                "responseOverride": {"status": 299, "bodySet": {"hit": True}},
            },
        )

    headers = header(row["req_header"]) if row["req_header"] else {}
    res = api.request(
        row["req_method"],
        rule.path + row["req_path_suffix"],
        headers=headers,
        data=row["req_body"] or None,
    )

    assert (res.status_code == 299) is (row["expect_hit"] == "true")
