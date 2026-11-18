"""The request as the engine sees it: a plain dict {method, path, headers, body} and
the header helpers that work on it."""

import re
from urllib.parse import urlparse


def make_req(method, path, headers, body=""):
    return {
        "method": method.upper(),
        "path": path,
        "headers": dict(headers),
        "body": body,
    }


def hget(headers, name):
    low = name.lower()
    for key, val in headers.items():
        if key.lower() == low:
            return val
    return None


def hset(headers, name, value):
    hdel(headers, name)
    headers[name] = value


def hdel(headers, name):
    low = name.lower()
    for key in [k for k in headers if k.lower() == low]:
        del headers[key]


def req_url(req):
    """host + path, with a canonical http:// in front even for https requests."""
    host = hget(req["headers"], "Host") or "127.0.0.1"
    return f"http://{host}{req['path']}"


def bare(url):
    """A match string without its scheme, so https://x/y and http://x/y both work."""
    return re.sub(r"^https?://", "", url)


def req_from_url(method, url, headers=None, body=""):
    """Build a request dict from a full URL (tester input)."""
    parts = urlparse(url)
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    hdrs = dict(headers or {})
    if parts.netloc and hget(hdrs, "Host") is None:
        hdrs["Host"] = parts.netloc
    return make_req(method or "GET", path, hdrs, body)
