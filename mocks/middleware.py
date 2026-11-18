from .mocking import proxied, reply


class MockMiddleware:
    """The two things that happen before url routing: a request aimed at a foreign
    host (proxy mode, or inside an intercepted https tunnel) never touches the admin
    routes, and a direct OPTIONS is a CORS preflight."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        origin = request.META.get("mockproxy.origin")
        if origin:
            return proxied(request, origin)
        if request.method == "OPTIONS":
            return reply(
                204,
                headers={
                    "Access-Control-Allow-Methods": "*",
                    "Access-Control-Allow-Headers": "*",
                },
            )
        return self.get_response(request)
