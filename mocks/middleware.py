from .apis.helpers import reply


class MockMiddleware:
    """A direct OPTIONS is a CORS preflight, whatever the path."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method == "OPTIONS":
            return reply(
                204,
                headers={
                    "Access-Control-Allow-Methods": "*",
                    "Access-Control-Allow-Headers": "*",
                },
            )
        return self.get_response(request)
