"""A direct request nothing else claimed: the pause switch, the rules, a 404."""

from ..services import messages
from ..services.decisions import decide
from ..state import ENGINE
from .helpers import body_of, raw_headers, raw_path, reply


def mock(request):
    """A direct request nothing else claimed: the pause switch, the rules, a 404.
    A disconnect rule cannot close mitmdump's socket from here, so it asks the addon
    to (an empty 204 carrying the hangup header)."""
    req = messages.make_req(
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
