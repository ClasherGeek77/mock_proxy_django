"""The socket layer django does not have: a development-grade WSGI server taught the
two things a proxy needs.

    absolute-URI request line   GET http://host/x HTTP/1.1  -> handed to django with
                                the foreign origin in environ["mockproxy.origin"]
    CONNECT                     opened up with a certificate from the local CA when
                                the client starts a TLS handshake, the requests inside
                                are served like proxied ones; any other tunnel (or
                                --no-mitm) is a blind relay

Everything else, including answering, is django's.
"""

import select
import socket
import ssl
from urllib.parse import urlparse

from django.core.servers.basehttp import (
    ServerHandler,
    ThreadedWSGIServer,
    WSGIRequestHandler,
)

from . import tlsca
from .state import CA, ENGINE, VERSION

METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "CONNECT")


class Out:
    """wfile for a TLS socket: every write goes out whole."""

    def __init__(self, sock):
        self.sock = sock

    def write(self, data):
        self.sock.sendall(data)
        return len(data)

    def flush(self):
        pass


class MockServerHandler(ServerHandler):
    def finish_response(self):
        """A disconnect rule answers with nothing at all: the socket just closes."""
        if self.environ.get("mockproxy.hangup"):
            self.request_handler.hangup()  # pylint: disable=no-member
            self.close()
        else:
            super().finish_response()


class Handler(WSGIRequestHandler):
    server_version = "MockProxyDjango/" + VERSION
    mitm_host = None  # set while serving the requests inside an intercepted tunnel

    def log_message(self, format, *args):  # pylint: disable=redefined-builtin
        print(f"{self.address_string()} {format % args}", flush=True)

    # ------------------------------------------------------------ request in
    def handle_one_request(self):
        """django's own loop plus CONNECT and the method whitelist."""
        self.raw_requestline = self.rfile.readline(65537)
        if len(self.raw_requestline) > 65536:
            self.requestline = ""
            self.request_version = ""
            self.command = ""
            self.send_error(414)
            return
        if not self.parse_request():  # an error code has been sent, just exit
            return
        if self.command not in METHODS:
            self.send_error(501, f"Unsupported method ({self.command!r})")
            return
        if self.command == "CONNECT":
            self.tunnel()
            return
        handler = MockServerHandler(
            self.rfile, self.wfile, self.get_stderr(), self.get_environ()
        )
        handler.request_handler = self  # backpointer for logging & connection closing
        handler.run(self.server.get_app())

    def is_proxy_request(self):
        """An absolute-URI request line (GET http://host/x) aimed at another host."""
        parts = urlparse(self.path)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            return False
        own = self.server.server_address
        same_port = (parts.port or 80) == own[1]
        return not (same_port and parts.hostname in ("127.0.0.1", "localhost", own[0]))

    def split_target(self):
        """Cut an absolute-URI request line down to its path, return the foreign origin
        (scheme, host) in proxy mode, None for a direct call."""
        if self.mitm_host:  # inside an intercepted tunnel the path is relative
            return ("https", self.mitm_host)
        parts = urlparse(self.path)
        if not parts.scheme:
            return None
        origin = (parts.scheme, parts.netloc) if self.is_proxy_request() else None
        self.path = (parts.path or "/") + ("?" + parts.query if parts.query else "")
        return origin

    def get_environ(self):
        """What the app needs beyond plain wsgi: the foreign origin, and the request
        exactly as it came (wsgi unquotes the path and invents a Content-Type, the
        rules want the bytes the client sent)."""
        origin = self.split_target()
        env = super().get_environ()
        env["PATH_INFO"] = self.path.partition("?")[0]
        env["mockproxy.origin"] = origin
        env["mockproxy.path"] = self.path
        env["mockproxy.headers"] = dict(self.headers.items())
        return env

    # ------------------------------------------------------------ response out
    def hangup(self):
        self.close_connection = True
        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def send_json(self, status, text):
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        ENGINE.metrics.request(status)

    # ------------------------------------------------------------ CONNECT
    def tunnel(self):
        """CONNECT. With interception on, a TLS client is opened up so the rules see
        the https request inside; anything else is a blind tunnel (not mockable)."""
        host, _, port = self.path.rpartition(":")
        if not self.server.mitm:
            upstream = self.dial(host, port)
            if upstream is None:
                self.send_json(502, '{"error": "origin unreachable"}')
                return
            self.send_response(200, "Connection established")
            self.end_headers()
            self.relay(upstream)
            return
        self.send_response(200, "Connection established")
        self.end_headers()
        self.close_connection = True
        try:
            self.connection.settimeout(30)
            first = self.connection.recv(1, socket.MSG_PEEK)
        except OSError:
            return
        if first == b"\x16":  # a TLS hello
            self.intercept(host, port)
            return
        upstream = self.dial(host, port)
        if upstream:
            self.relay(upstream)

    @staticmethod
    def dial(host, port):
        try:
            return socket.create_connection((host, int(port)), timeout=10)
        except (OSError, ValueError):
            return None

    def relay(self, upstream):
        self.close_connection = True
        try:
            self.connection.settimeout(None)
            socks = [self.connection, upstream]
            while True:
                ready, _, _ = select.select(socks, [], [], 60)
                if not ready:
                    break
                for src in ready:
                    chunk = src.recv(65536)
                    if not chunk:
                        ENGINE.metrics.request("tunnel")
                        return
                    (upstream if src is self.connection else self.connection).sendall(
                        chunk
                    )
        except OSError:
            pass
        finally:
            upstream.close()
        ENGINE.metrics.request("tunnel")

    def intercept(self, host, port):
        """Terminate the client's TLS with a certificate for host, then serve the
        requests inside like proxied ones (rules first, the real origin after)."""
        try:
            ctx = CA.context(host)
            tls = ctx.wrap_socket(self.connection, server_side=True)
        except (tlsca.CAError, ssl.SSLError, OSError) as exc:
            print(f"https {host}: not intercepted ({exc})", flush=True)
            return
        saved = self.connection, self.rfile, self.wfile
        self.connection, self.rfile, self.wfile = tls, tls.makefile("rb"), Out(tls)
        self.mitm_host = host if port == "443" else f"{host}:{port}"
        self.close_connection = False
        try:
            while not self.close_connection:
                self.handle_one_request()
        except OSError:
            pass
        finally:
            self.mitm_host = None
            try:
                tls.close()
            except OSError:
                pass
            self.connection, self.rfile, self.wfile = saved
            self.close_connection = True


class MockServer(ThreadedWSGIServer):
    mitm = True


def make_server(host, port, app, mitm=True):
    srv = MockServer((host, port), Handler)
    srv.set_app(app)
    srv.mitm = mitm
    return srv
