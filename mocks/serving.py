"""The rule manager's server: django's development WSGI server, threaded, behind
mitmdump. It only ever sees loopback calls from the addon and from mitmdump routing
the proxy's own requests here, so the one thing it adds is the request exactly as
the client sent it (wsgi unquotes the path and rewrites header names, the rules want
the original bytes)."""

from django.core.servers.basehttp import ThreadedWSGIServer, WSGIRequestHandler

from .state import VERSION


class Handler(WSGIRequestHandler):
    server_version = "MockProxyDjango/" + VERSION

    def log_message(self, format, *args):  # pylint: disable=redefined-builtin
        pass  # mitmdump prints the traffic, this side stays quiet

    def get_environ(self):
        env = super().get_environ()
        env["mockproxy.path"] = self.path
        env["mockproxy.headers"] = dict(self.headers.items())
        return env


def make_server(host, port, app):
    srv = ThreadedWSGIServer((host, port), Handler)
    srv.set_app(app)
    return srv
