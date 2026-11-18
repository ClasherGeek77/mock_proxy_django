"""The rules: list, save, read, delete, toggle, export/import/test, history."""

from ..services.admin import norm_name
from ..state import ADMIN, ENGINE
from .helpers import json_body, query, strict
from .routing import ANY, NO_METHOD, route


@route("GET", "POST")
def rules(request):
    if request.method == "POST":
        return ADMIN.save(json_body(request), strict(request))
    every = query(request, "includeDeleted", "0") in ("1", "true")
    return 200, (ENGINE.store.rules() if every else ADMIN.live())


@route(*ANY)
def rule_item(request, name):
    method = request.method
    if name == "export" and method == "GET":
        return 200, ADMIN.live()
    if name == "import" and method == "POST":
        return ADMIN.import_rules(json_body(request), strict(request))
    if name == "test" and method == "POST":
        return ADMIN.test(json_body(request))
    name = norm_name(name)
    live = ADMIN.live()
    idx = ADMIN.find(live, name)
    if method == "GET":
        return (200, live[idx]) if idx >= 0 else (404, {"error": "no such rule"})
    if method == "PUT":
        doc = json_body(request)
        if not isinstance(doc, dict):
            return 400, {"success": False, "errors": ["rule must be a json object"]}
        doc["rule-name"] = name
        return ADMIN.save(doc, strict(request))
    if method == "DELETE":
        return ADMIN.delete(name)
    return NO_METHOD


@route("POST")
def rule_toggle(request, name):
    return ADMIN.toggle(norm_name(name))


@route("GET")
def history(request):
    return 200, ADMIN.history_of().get(norm_name(query(request, "name")), [])


@route("POST")
def history_restore(request, ident):
    return ADMIN.restore(ident)
