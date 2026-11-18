"""Stored rule content: the editor's list/put/delete and the public GET."""

from ..services import content
from ..services.admin import NAME_OK
from ..state import ADMIN
from .helpers import body_of, reply
from .routing import ANY, NO_METHOD, route


@route("GET")
def content_list(request):
    return 200, ADMIN.content_names()


@route(*ANY)
def content_item(request, name):
    if NAME_OK.match(name):
        if request.method in ("PUT", "POST"):
            return ADMIN.content_put(name, body_of(request))
        if request.method == "DELETE":
            return ADMIN.content_delete(name)
    return NO_METHOD


@route("GET", fallthrough=True)
def content_serve(request, name):
    found = content.read_content(name)
    if found is None:
        return 404, {"error": "no such content"}
    return reply(200, found[0], found[1])
