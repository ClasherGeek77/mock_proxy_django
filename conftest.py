"""Test fixtures. The suite owns its server: `manage.py runmock` is started on a free
port with its state in a temp dir seeded from rules.json, so the checked-in seed rules
are never touched and no manual start is needed.

    MOCK_URL=http://127.0.0.1:38800 ./run_tests.sh
        test an already running server instead (the live-reload test skips, it
        needs the server's data dir)
"""

import http.server
import json
import os
import shutil
import socket
import subprocess  # nosec B404
import sys
import tempfile
import threading
import time
import uuid

import pytest
import requests

from mocks import tlsca

HERE = os.path.dirname(os.path.abspath(__file__))


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Api(requests.Session):
    def __init__(self, base):
        super().__init__()
        self.base = base
        self.trust_env = False  # never route local calls through a proxy env

    def request(self, method, url, **kw):  # pylint: disable=arguments-differ
        kw.setdefault("timeout", 10)
        return super().request(
            method, self.base + url if url.startswith("/") else url, **kw
        )


@pytest.fixture(scope="session")
def server_dir():
    if os.environ.get("MOCK_URL"):
        yield None
        return
    tmp = tempfile.mkdtemp(prefix="mock_server_test_")
    shutil.copy(os.path.join(HERE, "rules.json"), tmp)
    yield tmp
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture(scope="session")
def base_url(server_dir):
    if os.environ.get("MOCK_URL"):
        yield os.environ["MOCK_URL"].rstrip("/")
        return
    port = free_port()
    # fixed argv, the only variable is a free port number we picked ourselves
    proc = subprocess.Popen(  # pylint: disable=consider-using-with  # nosec B603
        [sys.executable, "manage.py", "runmock", "--port", str(port)],
        cwd=HERE,
        # the https test origin is self-made
        env=dict(os.environ, MOCK_DATA_DIR=server_dir, MOCK_INSECURE="1"),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if (
                requests.get(
                    base + "/health", timeout=1, proxies={"http": None}
                ).status_code
                == 200
            ):
                break
        except requests.RequestException:
            time.sleep(0.1)
    else:
        proc.kill()
        pytest.fail(f"server did not come up on {base}")
    yield base
    proc.terminate()
    proc.wait(timeout=5)


@pytest.fixture(scope="session")
def api(base_url):
    return Api(base_url)


@pytest.fixture(autouse=True)
def mocking_on(api):
    yield
    api.post("/api/mock-state", json={"paused": False})


class Rule:
    def __init__(self, name, path):
        self.name = name
        self.path = path


@pytest.fixture
def make_rule(api):
    """make_rule(match_extra=None, **doc) -> Rule with a unique name and path."""
    made = []

    def factory(match_extra=None, **doc):
        token = uuid.uuid4().hex[:8]
        rule = Rule("t-" + token, "/t/" + token)
        body = {
            "rule-name": rule.name,
            "priority": 1,
            "match": dict({"urlContains": rule.path}, **(match_extra or {})),
        }
        body.update(doc)
        res = api.post("/api/rules", json=body)
        assert res.status_code in (200, 201), res.text
        made.append(rule.name)
        return rule

    yield factory
    for name in made:
        api.delete("/api/rules/" + name)


class Upstream(http.server.ThreadingHTTPServer):
    daemon_threads = True


def echo_handler():
    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def handle_any(self):
            size = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(size).decode() if size else ""
            out = json.dumps(
                {
                    "upstream": True,
                    "method": self.command,
                    "path": self.path,
                    "body": body,
                    "x-test": self.headers.get("X-Test"),
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        do_GET = do_POST = do_PUT = handle_any

    return H


@pytest.fixture(scope="session")
def upstream():
    """A tiny origin for proxyTo: 200 {"upstream": true, method, path, body, x-test}."""
    srv = Upstream(("127.0.0.1", 0), echo_handler())
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.fixture(scope="session")
def tls_upstream(tmp_path_factory):
    """The same origin over https, with a certificate nobody trusts (the server runs
    with MOCK_INSECURE, like a self-signed dev server)."""
    ctx = tlsca.CA(str(tmp_path_factory.mktemp("origin_ca"))).context("127.0.0.1")
    srv = Upstream(("127.0.0.1", 0), echo_handler())
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"https://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
