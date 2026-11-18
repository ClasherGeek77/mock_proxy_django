"""The two calls the mitmdump addon makes (proxy/addon.py), and the 405 for a wrong
method on a known /api path."""

import base64

from ..services import messages
from ..services.decisions import decide
from ..state import ENGINE
from .helpers import json_body
from .routing import ANY, NO_METHOD, route


@route("POST")
def proxy_decide(request):
    doc = json_body(request)
    verdict = decide(
        messages.make_req(doc["method"], doc["path"], doc["headers"], doc["body"])
    )
    if verdict["kind"] == "respond":
        verdict["body"] = base64.b64encode(verdict["body"]).decode("ascii")
    return 200, verdict


@route("POST")
def proxy_seen(request):
    ENGINE.metrics.request(json_body(request)["status"])
    return 200, {"success": True}


@route(*ANY)
def no(request):
    return NO_METHOD
