"""The routes of urls.py. Admin responses are not counted in the metrics."""

import http.client
import json
import os
import time
from functools import wraps
from urllib.parse import parse_qs

from django.http import HttpResponse

from . import engine, tlsca
from .admin import NAME_OK, norm_name
from .mocking import body_of, mock, reply
from .state import ADMIN, CA, ENGINE, VERSION

HERE = os.path.dirname(os.path.abspath(__file__))
ANY = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD")
NO_METHOD = (405, {"error": "method not allowed"})


def route(*allowed, fallthrough=False):
    """Method gate + json-error net. A wrong method is a 405, or, for the few routes
    that share their path with a mockable one (fallthrough), the rule engine's."""

    def decorate(func):
        @wraps(func)
        def view(request, **kwargs):
            if request.method not in allowed:
                return mock(request) if fallthrough else reply(*NO_METHOD)
            try:
                res = func(request, **kwargs)
            except ValueError as exc:
                return reply(400, {"success": False, "error": f"invalid json: {exc}"})
            return res if isinstance(res, HttpResponse) else reply(*res)

        return view

    return decorate


def query(request, key, default=""):
    return parse_qs(request.META.get("QUERY_STRING", "")).get(key, [default])[0]


def strict(request):
    return query(request, "strict", "0") in ("1", "true")


def json_body(request):
    body = body_of(request)
    return json.loads(body) if body.strip() else {}


# ------------------------------------------------------------------ plumbing
@route(*ANY)
def health(request):
    return 200, {"status": "ok"}


@route(*ANY)
def ui(request):
    with open(os.path.join(HERE, "ui.html"), "rb") as fh:
        return reply(200, fh.read(), "text/html; charset=utf-8")


@route(*ANY)
def ca_pem(request):
    try:
        CA.ensure()
    except tlsca.CAError as exc:
        return reply(503, {"error": str(exc)})
    with open(CA.cert, "rb") as fh:
        return reply(
            200,
            fh.read(),
            "application/x-x509-ca-cert",
            headers={"Content-Disposition": "attachment; filename=ca.pem"},
        )


@route("POST", fallthrough=True)
def send(request):
    """Send a request through this very proxy, so the page can try any url."""
    try:
        doc = json_body(request)
        url, method = str(doc["url"]), str(doc.get("method") or "GET").upper()
    except (ValueError, KeyError, TypeError, AttributeError):
        return 400, {"errors": ["need {method, url}"]}
    if not url.startswith(("http://", "https://")):
        return 400, {"errors": ["url must start with http(s)://"]}
    start = time.perf_counter()
    conn = http.client.HTTPConnection("127.0.0.1", int(request.META["SERVER_PORT"]))
    conn.timeout = 20
    try:
        conn.request(method, url)
        res = conn.getresponse()
        payload = {
            "status": res.status,
            "reason": res.reason,
            "body": res.read().decode("utf-8", "replace"),
        }
    except (OSError, http.client.HTTPException):
        payload = {"status": None, "error": "the connection was closed"}
    finally:
        conn.close()
    payload["ms"] = round((time.perf_counter() - start) * 1000)
    return 200, payload


@route("GET", fallthrough=True)
def version(request):
    return 200, {"name": "mock_proxy_django", "version": VERSION}


@route("GET", "POST")
def mock_state(request):
    if request.method == "POST":
        ENGINE.paused = bool(json_body(request).get("paused"))
    return 200, {"paused": ENGINE.paused}


@route("GET")
def metrics(request):
    snap = ENGINE.metrics.snapshot()
    snap["paused"] = ENGINE.paused
    snap["rules"] = len(ADMIN.live())
    return 200, snap


@route("POST")
def metrics_reset(request):
    ENGINE.metrics.reset()
    return 200, {"success": True}


# ------------------------------------------------------------------ rules
@route("GET", "POST")
def rules(request):
    if request.method == "POST":
        return ADMIN.save(json_body(request), strict(request))
    every = query(request, "includeDeleted", "0") in ("1", "true")
    return 200, (ENGINE.store.rules() if every else ADMIN.live())


@route(*ANY)
def rule_item(request, name):
    method = request.method
    if name == "export" and method == "GET":
        return 200, ADMIN.live()
    if name == "import" and method == "POST":
        return ADMIN.import_rules(json_body(request), strict(request))
    if name == "test" and method == "POST":
        return ADMIN.test(json_body(request))
    name = norm_name(name)
    live = ADMIN.live()
    idx = ADMIN.find(live, name)
    if method == "GET":
        return (200, live[idx]) if idx >= 0 else (404, {"error": "no such rule"})
    if method == "PUT":
        doc = json_body(request)
        if not isinstance(doc, dict):
            return 400, {"success": False, "errors": ["rule must be a json object"]}
        doc["rule-name"] = name
        return ADMIN.save(doc, strict(request))
    if method == "DELETE":
        return ADMIN.delete(name)
    return NO_METHOD


@route("POST")
def rule_toggle(request, name):
    return ADMIN.toggle(norm_name(name))


@route("GET")
def history(request):
    return 200, ADMIN.history_of().get(norm_name(query(request, "name")), [])


@route("POST")
def history_restore(request, ident):
    return ADMIN.restore(ident)


# ------------------------------------------------------------------ rule content
@route("GET")
def content_list(request):
    return 200, ADMIN.content_names()


@route(*ANY)
def content_item(request, name):
    if NAME_OK.match(name):
        if request.method in ("PUT", "POST"):
            return ADMIN.content_put(name, body_of(request))
        if request.method == "DELETE":
            return ADMIN.content_delete(name)
    return NO_METHOD


@route("GET", fallthrough=True)
def content_serve(request, name):
    found = engine.read_content(name)
    if found is None:
        return 404, {"error": "no such content"}
    return reply(200, found[0], found[1])


@route(*ANY)
def no(request):
    return NO_METHOD
