"""What happens to one request, as data: answer it, drop it or let it through. The
mitmdump addon asks for this over http, the direct-request fallback calls it in
process."""

from ..state import ENGINE
from . import actions
from .messages import hset


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
            hset(out, key, val)
    return out


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
        status, headers, payload = actions.forward(out["req"], out["proxyTo"])
    else:
        return {"kind": "none", "req": out["req"]}
    ENGINE.metrics.request(status)
    return {
        "kind": "respond",
        "status": status,
        "headers": shape(headers),
        "body": payload,
    }
