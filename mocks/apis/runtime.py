"""The pause switch and the metrics."""

from ..state import ADMIN, ENGINE
from .helpers import json_body
from .routing import route


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
