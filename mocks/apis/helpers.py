"""Reading a request and shaping a response, shared by every api module."""

import json
from urllib.parse import parse_qs

from django.http import HttpResponse

from ..services.decisions import shape
from ..state import ENGINE


def query(request, key, default=""):
    return parse_qs(request.META.get("QUERY_STRING", "")).get(key, [default])[0]


def strict(request):
    return query(request, "strict", "0") in ("1", "true")


def json_body(request):
    body = body_of(request)
    return json.loads(body) if body.strip() else {}


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


def raw_path(request):
    return request.META.get("mockproxy.path") or request.get_full_path()


def raw_headers(request):
    return request.META.get("mockproxy.headers") or dict(request.headers.items())


def body_of(request):
    return request.body.decode("utf-8", "replace")
