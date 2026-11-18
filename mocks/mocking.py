"""The mock itself: ask the rule engine what happens to a request, for the mitmdump
addon (proxied traffic) and for direct requests no route claimed."""

import json

from django.http import HttpResponse

from . import engine
from .state import ENGINE

# never copied from a rule onto a response: the transport frames the message itself
# (wsgiref refuses the hop-by-hop ones outright)
NOT_COPIED = {
    "content-length",
    "transfer-encoding",
    "connection",
    "server",
    "date",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "upgrade",
}


def shape(headers, ctype="application/json"):
    """The headers of a mocked response: a json default, open CORS, whatever the rule
    set on top (hop-by-hop ones dropped, the transport frames the message itself)."""
    out = {"Content-Type": ctype, "Access-Control-Allow-Origin": "*"}
    for key, val in (headers or {}).items():
        if key.lower() not in NOT_COPIED:
            engine.hset(out, key, val)
    return out


def reply(status, body=b"", ctype="application/json", headers=None, count=False):
    """One place that shapes every response. count=True feeds /api/metrics (admin,
    ui and health traffic is not counted, mocked and proxied traffic is)."""
    if isinstance(body, (dict, list)):
        body = json.dumps(body)
    if isinstance(body, str):
        body = body.encode("utf-8")
    resp = HttpResponse(body, status=status)
    for key, val in shape(headers, ctype).items():
        resp[key] = val
    resp["Content-Length"] = str(len(body))  # keeps the connection alive
    if count:
        ENGINE.metrics.request(status)
    return resp


# serving.py leaves the exact request line and header names in META, a plain wsgi
# server does not: fall back to what django rebuilds
def raw_path(request):
    return request.META.get("mockproxy.path") or request.get_full_path()


def raw_headers(request):
    return request.META.get("mockproxy.headers") or dict(request.headers.items())


def body_of(request):
    return request.body.decode("utf-8", "replace")


def decide(req):
    """Run the rules on one request and say what happens to it. Metrics are counted
    here for everything that is answered or dropped; what is let through is counted by
    the addon once the real origin has answered.

    {"kind": "disconnect"}
    {"kind": "respond", "status", "headers", "body": bytes}
    {"kind": "none", "req": the request, rule overrides applied}
    """
    out = {"kind": "none", "req": req}
    if not ENGINE.paused:  # paused = stop mocking, the proxy keeps relaying
        out = ENGINE.apply(req)
    if out["kind"] == "disconnect":
        ENGINE.metrics.request("disconnect")
        return {"kind": "disconnect"}
    if out["kind"] == "synthetic":
        status, headers, payload = out["response"]
    elif out["kind"] == "forward":
        status, headers, payload = engine.forward(out["req"], out["proxyTo"])
    else:
        return {"kind": "none", "req": out["req"]}
    ENGINE.metrics.request(status)
    return {
        "kind": "respond",
        "status": status,
        "headers": shape(headers),
        "body": payload,
    }


def mock(request):
    """A direct request nothing else claimed: the pause switch, the rules, a 404.
    A disconnect rule cannot close mitmdump's socket from here, so it asks the addon
    to (an empty 204 carrying the hangup header)."""
    req = engine.make_req(
        request.method, raw_path(request), raw_headers(request), body_of(request)
    )
    if ENGINE.paused:
        return reply(503, {"mocking": "paused"}, count=True)
    verdict = decide(req)
    if verdict["kind"] == "disconnect":
        return reply(204, headers={"X-Mock-Hangup": "1"})
    if verdict["kind"] == "respond":
        return reply(verdict["status"], verdict["body"], headers=verdict["headers"])
    return reply(404, {"error": "not found"}, count=True)
