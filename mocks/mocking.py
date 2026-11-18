"""The mock itself: turn what the rule engine decided into a django response, relay
proxied requests, and answer direct requests no route claimed."""

import json

from django.http import HttpResponse

from . import engine
from .state import ENGINE

# never copied from an origin or a rule onto our own response: django/wsgi frame the
# message themselves (wsgiref refuses the hop-by-hop ones outright)
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


def reply(status, body=b"", ctype="application/json", headers=None, count=False):
    """One place that shapes every response. count=True feeds /api/metrics (admin,
    ui and health traffic is not counted, mocked and proxied traffic is)."""
    if isinstance(body, (dict, list)):
        body = json.dumps(body)
    if isinstance(body, str):
        body = body.encode("utf-8")
    resp = HttpResponse(body, status=status, content_type=ctype)
    resp["Content-Length"] = str(len(body))  # keeps the connection alive
    resp["Access-Control-Allow-Origin"] = "*"
    for key, val in (headers or {}).items():
        if key.lower() not in NOT_COPIED:
            resp[key] = val
    if count:
        ENGINE.metrics.request(status)
    return resp


# the serving layer (serving.py) leaves the exact request line and header names in
# META, a plain wsgi server does not: fall back to what django rebuilds
def raw_path(request):
    return request.META.get("mockproxy.path") or request.get_full_path()


def raw_headers(request):
    return request.META.get("mockproxy.headers") or dict(request.headers.items())


def body_of(request):
    return request.body.decode("utf-8", "replace")


def answer_rule(request, out):
    """Build what the winning rule asks for; None when it left the request alone."""
    if out["kind"] == "disconnect":
        ENGINE.metrics.request("disconnect")
        request.META["mockproxy.hangup"] = (
            True  # serving.py closes the socket unanswered
        )
        return HttpResponse(status=204)
    if out["kind"] == "synthetic":
        status, headers, payload = out["response"]
        return reply(status, payload, headers=headers, count=True)
    if out["kind"] == "forward":
        status, headers, payload = engine.forward(out["req"], out["proxyTo"])
        return reply(status, payload, headers=headers, count=True)
    return None


def proxied(request, origin):
    """Proxy mode: rules first, the real origin for everything they leave alone."""
    hdrs = {
        k: v
        for k, v in raw_headers(request).items()
        if k.lower() not in ("proxy-connection", "proxy-authorization")
    }
    engine.hset(hdrs, "Host", origin[1])
    req = engine.make_req(request.method, raw_path(request), hdrs, body_of(request))
    out = {"kind": "none", "req": req}
    if not ENGINE.paused:  # paused = stop mocking, the proxy keeps relaying
        out = ENGINE.apply(req)
    answer = answer_rule(request, out)
    if answer:
        return answer
    status, headers, payload = engine.passthrough(out["req"], *origin)
    return reply(status, payload, headers=headers, count=True)


def mock(request):
    """A direct request nothing else claimed: the pause switch, the rules, a 404."""
    req = engine.make_req(
        request.method, raw_path(request), raw_headers(request), body_of(request)
    )
    if ENGINE.paused:
        return reply(503, {"mocking": "paused"}, count=True)
    answer = answer_rule(request, ENGINE.apply(req))
    return answer or reply(404, {"error": "not found"}, count=True)
