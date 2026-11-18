"""Plumbing: health, the editor page, the CA download, the try-it sender, version."""

import http.client
import os
import time

from ..conf import CA_CERT, VERSION
from ..state import PUBLIC
from .helpers import json_body, reply
from .routing import ANY, route

WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")


@route(*ANY)
def health(request):
    return 200, {"status": "ok"}


@route(*ANY)
def ui(request):
    with open(os.path.join(WEB, "ui.html"), "rb") as fh:
        return reply(200, fh.read(), "text/html; charset=utf-8")


@route(*ANY)
def ca_pem(request):
    """The CA mitmdump signs its https certificates with (made on its first start)."""
    if not os.path.exists(CA_CERT):
        return reply(503, {"error": "the proxy has not made its CA yet"})
    with open(CA_CERT, "rb") as fh:
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
    port = PUBLIC["port"] or int(request.META["SERVER_PORT"])
    conn = http.client.HTTPConnection("127.0.0.1", port)
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
