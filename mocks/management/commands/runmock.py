import os

from django.core.management.base import BaseCommand
from django.core.wsgi import get_wsgi_application

from mocks import engine, serving


class Command(BaseCommand):
    help = "Start the mock proxy: api, ui, rules, http proxy, https interception"
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--host", default="127.0.0.1")
        parser.add_argument("--port", type=int, default=38800)
        parser.add_argument(
            "--no-mitm",
            action="store_true",
            help="relay https blindly, do not open it up",
        )
        parser.add_argument(
            "--insecure",
            action="store_true",
            help="do not verify the certificates of real origins",
        )

    def handle(self, *args, **opts):
        engine.VERIFY_ORIGINS = not (
            opts["insecure"] or os.environ.get("MOCK_INSECURE")
        )
        srv = serving.make_server(
            opts["host"], opts["port"], get_wsgi_application(), not opts["no_mitm"]
        )
        print(f"mock server on http://{opts['host']}:{opts['port']}", flush=True)
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass
