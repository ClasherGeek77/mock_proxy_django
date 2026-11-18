"""mitmproxy addon: the traffic half of the mock proxy.

mitmdump owns everything on the wire (sockets, CONNECT, the CA, TLS interception,
http/1 and http/2, the real upstream call). This addon owns one decision per request,
and gets it from the django rule manager (POST api/proxy/decide):

    respond      answer now, the origin is never called (a mocked response)
    disconnect   kill the connection without a reply
    none         let it through, with whatever request overrides the rule made

It runs inside mitmdump's interpreter, which has no django: stdlib + mitmproxy only.
A request aimed at the proxy itself (the admin api, the ui, a directly mocked path)
is not proxied, it is routed to the django server.
"""

import asyncio
import base64
import json
import urllib.request

from mitmproxy import ctx, http  # pylint: disable=import-error

LOOPBACK = ("127.0.0.1", "localhost", "::1")
HANGUP = "X-Mock-Hangup"  # django asks for a disconnect on a directly mocked path
NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def post(path, doc):
    """One blocking json call to the rule manager, never through a proxy env."""
    call = urllib.request.Request(
        ctx.options.mock_manager + path,
        data=json.dumps(doc).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with NO_PROXY.open(call, timeout=60) as res:  # delayMs can be up to 30 s
        return json.load(res)


async def ask(path, doc):
    """The same call off the event loop, so a delay rule stalls one flow, not all."""
    return await asyncio.get_running_loop().run_in_executor(None, post, path, doc)


def authority(req):
    default = 443 if req.scheme == "https" else 80
    return req.host if req.port == default else f"{req.host}:{req.port}"


class MockProxy:
    def load(self, loader):
        loader.add_option(
            "mock_manager", str, "", "base url of the django rule manager"
        )

    def is_direct(self, flow):
        """A request for the proxy's own port, not for a site behind it."""
        req = flow.request
        return req.host in LOOPBACK and req.port == ctx.options.listen_port

    def to_manager(self, flow):
        req = flow.request
        host_header = req.headers.get("Host")
        req.scheme, req.host = "http", "127.0.0.1"
        req.port = int(ctx.options.mock_manager.rsplit(":", 1)[1])
        if host_header:
            req.headers["Host"] = host_header
        flow.metadata["direct"] = True

    async def request(self, flow):
        if self.is_direct(flow):
            self.to_manager(flow)
            return
        req = flow.request
        headers = {k: v for k, v in req.headers.items() if k.lower() != "host"}
        headers["Host"] = authority(req)  # the rules match on host + path
        sent = {
            "method": req.method,
            "path": req.path,
            "headers": headers,
            "body": req.get_text(strict=False) or "",
        }
        verdict = await ask("/api/proxy/decide", sent)
        if verdict["kind"] == "disconnect":
            flow.kill()
        elif verdict["kind"] == "respond":
            flow.response = http.Response.make(
                verdict["status"],
                base64.b64decode(verdict["body"]),
                verdict["headers"],
            )
        else:
            flow.metadata["relayed"] = True
            self.rewrite(req, sent, verdict["req"])

    @staticmethod
    def rewrite(req, sent, new):
        """Carry a rule's requestOverride onto the request that goes upstream. Only
        what the rule changed is touched, so untouched bytes stay as they came. The
        Host header follows the connection, as it always did."""
        if new["body"] != sent["body"]:
            req.text = new["body"]
        if new["method"] != sent["method"]:
            req.method = new["method"]
        if new["path"] != sent["path"]:
            req.path = new["path"]
        old, now = sent["headers"], new["headers"]
        for key in old.keys() - now.keys():
            if key.lower() != "host":
                del req.headers[key]
        for key, val in now.items():
            if old.get(key) != val and key.lower() != "host":
                req.headers[key] = val

    async def response(self, flow):
        if flow.metadata.get("direct") and flow.response.headers.get(HANGUP):
            flow.kill()
        elif flow.metadata.get("relayed"):
            await ask("/api/proxy/seen", {"status": flow.response.status_code})

    async def error(self, flow):
        if flow.metadata.get("relayed"):
            await ask("/api/proxy/seen", {"status": 502})

    async def tcp_end(self, flow):
        await ask("/api/proxy/seen", {"status": "tunnel"})


addons = [MockProxy()]
