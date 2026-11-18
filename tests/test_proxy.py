import os
import socket
import subprocess  # nosec B404
import sys
import time
import uuid

import pytest
import requests

from conftest import HERE, free_port


@pytest.fixture
def via(base_url):
    """A client that uses the mock as its http proxy."""
    sess = requests.Session()
    sess.trust_env = False
    sess.proxies = {"http": base_url}
    return sess


def test_rule_mocks_a_host_that_does_not_exist(via, make_rule):
    rule = make_rule(
        match_extra={"urlContains": "www.yahoo.com"},
        responseOverride={"status": 418, "bodySet": {"mocked": True}},
    )
    del rule
    res = via.get("http://www.yahoo.com/anything", timeout=10)
    assert res.status_code == 418
    assert res.json() == {"mocked": True}


def test_unmatched_request_reaches_the_real_origin(via, upstream):
    res = via.get(upstream + "/real/path?q=1", timeout=10)
    assert res.status_code == 200
    assert res.json()["upstream"] is True
    assert res.json()["path"] == "/real/path?q=1"


def test_method_headers_and_body_survive_the_trip(via, upstream):
    res = via.post(upstream + "/x", data="payload", headers={"X-Test": "1"}, timeout=10)
    out = res.json()
    assert (out["method"], out["body"], out["x-test"]) == ("POST", "payload", "1")


def test_rule_can_rewrite_then_the_origin_answers(via, upstream, make_rule):
    token = uuid.uuid4().hex[:8]
    make_rule(
        match_extra={"urlContains": "/rw-" + token},
        proxyTo=upstream,
        requestOverride={"headersReplace": {"X-Test": "rewritten"}},
    )
    res = via.get(upstream + "/rw-" + token, timeout=10)
    assert res.json()["x-test"] == "rewritten"


def test_a_rule_only_fires_for_its_own_host(via, upstream, make_rule):
    rule = make_rule(
        match_extra={"urlContains": "only-here.invalid"},
        responseOverride={"status": 202},
    )
    assert (
        via.get("http://only-here.invalid" + rule.path, timeout=10).status_code == 202
    )
    assert via.get(upstream + rule.path, timeout=10).json()["upstream"] is True


def test_admin_paths_on_other_hosts_are_not_admin(via, upstream):
    res = via.get(upstream + "/api/rules", timeout=10)
    assert res.json()["upstream"] is True


def test_pause_stops_mocking_but_the_proxy_keeps_relaying(
    via, api, upstream, make_rule
):
    rule = make_rule(responseOverride={"status": 418})
    assert via.get(upstream + rule.path, timeout=10).status_code == 418
    api.post("/api/mock-state", json={"paused": True})
    res = via.get(upstream + rule.path, timeout=10)
    assert res.status_code == 200 and res.json()["upstream"] is True


def test_hangup_rule_works_through_the_proxy(via, make_rule):
    rule = make_rule(disconnect=True)
    with pytest.raises(requests.ConnectionError):
        via.get("http://hang.invalid" + rule.path, timeout=10)


def test_unreachable_origin_is_a_502(via):
    res = via.get("http://127.0.0.1:1/nothing", timeout=10)
    assert res.status_code == 502
    assert "Connect call failed" in res.text  # mitmproxy's own error page


def test_proxy_request_to_the_mock_itself_is_still_direct(via, base_url):
    assert via.get(base_url + "/health", timeout=10).json() == {"status": "ok"}


def test_proxied_hits_show_in_metrics(via, api, make_rule):
    rule = make_rule(responseOverride={"status": 203})
    api.post("/api/metrics/reset")
    via.get("http://counted.invalid" + rule.path, timeout=10)
    assert api.get("/api/metrics").json()["byRule"][rule.name]["hits"] == 1


def test_connect_to_a_plain_http_port_relays_what_follows(base_url, upstream):
    host, port = base_url.rsplit("//", 1)[1].split(":")
    target = upstream.rsplit("//", 1)[1]
    with socket.create_connection((host, int(port)), timeout=10) as sock:
        sock.sendall(f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n\r\n".encode())
        assert b"200" in sock.recv(4096).split(b"\r\n")[0]
        sock.sendall(
            f"GET /tun HTTP/1.1\r\nHost: {target}\r\nConnection: close\r\n\r\n".encode()
        )
        data = b""
        while chunk := sock.recv(4096):
            data += chunk
    assert b'"path": "/tun"' in data


def test_connect_to_a_dead_port_is_a_502_at_the_connect(base_url):
    host, port = base_url.rsplit("//", 1)[1].split(":")
    with socket.create_connection((host, int(port)), timeout=10) as sock:
        sock.sendall(b"CONNECT 127.0.0.1:1 HTTP/1.1\r\nHost: 127.0.0.1:1\r\n\r\n")
        assert b"502" in sock.recv(4096).split(b"\r\n")[0]


@pytest.fixture
def no_mitm_port(tmp_path):
    """A second mock proxy that tunnels https untouched, with its own empty state."""
    port = free_port()
    # fixed argv, a free port we picked; the state goes to a temp dir
    proc = subprocess.Popen(  # pylint: disable=consider-using-with  # nosec B603
        [sys.executable, "manage.py", "runmock", "--port", str(port), "--no-mitm"],
        cwd=HERE,
        env=dict(os.environ, MOCK_DATA_DIR=str(tmp_path)),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(300):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=1).close()
                break
            except OSError:
                time.sleep(0.1)
        yield port
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_no_mitm_answers_a_dead_connect_with_502(no_mitm_port):
    with socket.create_connection(("127.0.0.1", no_mitm_port), timeout=10) as sock:
        sock.sendall(b"CONNECT 127.0.0.1:1 HTTP/1.1\r\nHost: 127.0.0.1:1\r\n\r\n")
        assert b"502" in sock.recv(4096).split(b"\r\n")[0]


def test_no_mitm_leaves_https_alone_so_its_rules_cannot_fire(
    no_mitm_port, tls_upstream
):
    base = f"http://127.0.0.1:{no_mitm_port}"
    sess = requests.Session()
    sess.trust_env = False
    rule = {
        "rule-name": "would-mock",
        "match": {"urlContains": "/untouched"},
        "responseOverride": {"status": 418},
    }
    assert sess.post(base + "/api/rules", json=rule, timeout=10).status_code in (
        200,
        201,
    )
    sess.proxies = {"https": base}
    res = sess.get(tls_upstream + "/untouched", verify=False, timeout=10)
    assert res.status_code == 200 and res.json()["upstream"] is True


# ------------------------------------------------------------------ https
@pytest.fixture
def ca_file(base_url, tmp_path):
    res = requests.get(base_url + "/ca.pem", timeout=10, proxies={"http": None})
    assert res.status_code == 200
    path = tmp_path / "ca.pem"
    path.write_bytes(res.content)
    return str(path)


@pytest.fixture
def secure(base_url, ca_file):
    """A client that uses the mock as its proxy for https and trusts its CA."""
    sess = requests.Session()
    sess.trust_env = False
    sess.proxies = {"https": base_url}
    sess.verify = ca_file
    return sess


def test_the_ca_certificate_can_be_downloaded(base_url):
    res = requests.get(base_url + "/ca.pem", timeout=10, proxies={"http": None})
    assert res.text.startswith("-----BEGIN CERTIFICATE-----")
    assert "ca.pem" in res.headers["Content-Disposition"]


def test_rule_mocks_an_https_host_for_a_client_that_trusts_the_ca(secure, make_rule):
    rule = make_rule(
        match_extra={"urlContains": "www.yahoo.com"},
        responseOverride={"status": 503, "bodySet": {"mocked": True}},
    )
    res = secure.get("https://www.yahoo.com" + rule.path, timeout=10)
    assert res.status_code == 503
    assert res.json() == {"mocked": True}


def test_a_client_that_ignores_ssl_gets_the_mock_too(base_url, make_rule):
    rule = make_rule(
        match_extra={"urlContains": "www.yahoo.com"},
        responseOverride={"status": 429},
    )
    sess = requests.Session()
    sess.trust_env = False
    sess.proxies = {"https": base_url}
    res = sess.get("https://www.yahoo.com" + rule.path, verify=False, timeout=10)
    assert res.status_code == 429


def test_a_client_that_does_not_trust_the_ca_is_refused(base_url, make_rule):
    rule = make_rule(match_extra={"urlContains": "www.yahoo.com"})
    sess = requests.Session()
    sess.trust_env = False
    sess.proxies = {"https": base_url}
    with pytest.raises(requests.exceptions.SSLError):
        sess.get("https://www.yahoo.com" + rule.path, timeout=10)


def test_a_rule_written_with_https_in_it_matches(secure, make_rule):
    token = uuid.uuid4().hex[:8]
    make_rule(
        match_extra={"urlContains": f"https://www.yahoo.com/s-{token}"},
        responseOverride={"status": 202},
    )
    assert secure.get(f"https://www.yahoo.com/s-{token}", timeout=10).status_code == 202


def test_https_hangup_rule_gives_no_reply(secure, make_rule):
    rule = make_rule(match_extra={"urlContains": "www.yahoo.com"}, disconnect=True)
    with pytest.raises(requests.ConnectionError):
        secure.get("https://www.yahoo.com" + rule.path, timeout=10)


def test_unmatched_https_request_reaches_the_real_origin(secure, tls_upstream):
    res = secure.get(tls_upstream + "/real?q=1", timeout=10)
    assert res.json()["upstream"] is True
    assert res.json()["path"] == "/real?q=1"


def test_https_post_body_survives_the_trip(secure, tls_upstream):
    res = secure.post(tls_upstream + "/x", data="payload", timeout=10)
    assert res.json()["body"] == "payload"


def test_pause_stops_mocking_https_but_keeps_relaying(
    secure, api, tls_upstream, make_rule
):
    rule = make_rule(responseOverride={"status": 418})
    assert secure.get(tls_upstream + rule.path, timeout=10).status_code == 418
    api.post("/api/mock-state", json={"paused": True})
    assert secure.get(tls_upstream + rule.path, timeout=10).json()["upstream"] is True


def test_many_https_requests_in_a_row(secure, make_rule):
    rule = make_rule(
        match_extra={"urlContains": "www.yahoo.com"}, responseOverride={"status": 204}
    )
    codes = {
        secure.get("https://www.yahoo.com" + rule.path, timeout=10).status_code
        for _ in range(5)
    }
    assert codes == {204}
