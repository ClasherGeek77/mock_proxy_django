"""The method gate every view goes through."""

from functools import wraps

from django.http import HttpResponse

from .fallback import mock
from .helpers import reply

ANY = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD")
NO_METHOD = (405, {"error": "method not allowed"})


def route(*allowed, fallthrough=False):
    """Method gate + json-error net. A wrong method is a 405, or, for the few routes
    that share their path with a mockable one (fallthrough), the rule engine's."""

    def decorate(func):
        @wraps(func)
        def view(request, **kwargs):
            if request.method not in allowed:
                return mock(request) if fallthrough else reply(*NO_METHOD)
            try:
                res = func(request, **kwargs)
            except ValueError as exc:
                return reply(400, {"success": False, "error": f"invalid json: {exc}"})
            return res if isinstance(res, HttpResponse) else reply(*res)

        return view

    return decorate
