"""What a winning rule does: macros, request overrides, synthetic responses and the
proxyTo replay."""

import json
import urllib.error
import urllib.request
from urllib.parse import urlparse

from .content import fetch_body
from .messages import hdel, hget, hset


def set_json_path(obj, path, value):
    keys = path.split(".")
    for key in keys[:-1]:
        obj = obj.setdefault(key, {})
    obj[keys[-1]] = value


def macro(rule):
    return json.loads(json.dumps(rule).replace("{host}", "127.0.0.1"))


def action_of(rule):
    if rule.get("disconnect"):
        return "disconnect"
    if rule.get("responseOverride"):
        return "synthetic-response"
    if rule.get("proxyTo"):
        return "proxy"
    if rule.get("requestOverride"):
        return "modify-request"
    if rule.get("delayMs", 0) > 0:
        return "delay"
    return "match"


def apply_request_override(req, over):
    req = {
        "method": req["method"],
        "path": req["path"],
        "headers": dict(req["headers"]),
        "body": req["body"],
    }
    if over.get("url"):
        parts = urlparse(over["url"])
        req["path"] = (parts.path or "/") + ("?" + parts.query if parts.query else "")
    if over.get("method"):
        req["method"] = over["method"].upper()
    for key, val in (over.get("headersReplace") or {}).items():
        hset(req["headers"], key, val)
    for key in over.get("headersRemove") or []:
        hdel(req["headers"], key)
    if over.get("bodyReplace"):
        try:
            body = json.loads(req["body"])
            for path, val in over["bodyReplace"].items():
                set_json_path(body, path, val)
            req["body"] = json.dumps(body)
        except (ValueError, AttributeError, TypeError):
            pass  # same as the original: a body that is not json is left alone
    if over.get("bodySet") is not None:
        bs = over["bodySet"]
        req["body"] = bs if isinstance(bs, str) else json.dumps(bs)
    if over.get("rawBodyReplace"):
        req["body"] = over["rawBodyReplace"]
    return req


def synth_response(over):
    status = int(over.get("status", 200))
    headers = dict(over.get("headersReplace") or {})
    ctype = None
    if over.get("bodyHTML"):
        body, ctype = fetch_body(over["bodyHTML"])
    elif over.get("bodySet") is not None:
        bs = over["bodySet"]
        if isinstance(bs, str):
            body = bs.encode("utf-8")
        else:
            body = json.dumps(bs).encode("utf-8")
            ctype = "application/json"
    else:
        body = b""
    if ctype and hget(headers, "Content-Type") is None:
        headers["Content-Type"] = ctype
    return status, headers, body


def forward(req, base):
    """proxyTo: replay the (possibly overridden) request against another origin."""
    if urlparse(base).scheme not in ("http", "https"):
        err = {"error": "proxy failed", "detail": "proxyTo must be an http(s) url"}
        return 502, {"Content-Type": "application/json"}, json.dumps(err).encode()
    skip = {"host", "content-length", "connection", "accept-encoding"}
    hdrs = {k: v for k, v in req["headers"].items() if k.lower() not in skip}
    data = req["body"].encode("utf-8") if req["body"] else None
    call = urllib.request.Request(
        base.rstrip("/") + req["path"], data=data, headers=hdrs, method=req["method"]
    )
    try:
        # scheme is checked above: http(s) only, never file:/ or custom
        with urllib.request.urlopen(call, timeout=5) as resp:  # nosec B310
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()
    except (urllib.error.URLError, OSError) as exc:
        return (
            502,
            {"Content-Type": "application/json"},
            json.dumps({"error": "proxy failed", "detail": str(exc)}).encode(),
        )
