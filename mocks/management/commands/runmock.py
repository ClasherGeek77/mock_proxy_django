import os
import signal
import threading

from django.core.management.base import BaseCommand, CommandError
from django.core.wsgi import get_wsgi_application

from mocks import mitm, serving
from mocks.state import CA_DIR, PUBLIC


def stop(*_):
    raise KeyboardInterrupt  # a plain kill ends mitmdump too, never an orphan


class Command(BaseCommand):
    help = "Start the mock proxy: mitmdump in front, the django rule manager behind"
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--host", default="127.0.0.1")
        parser.add_argument("--port", type=int, default=38800)
        parser.add_argument(
            "--no-mitm",
            action="store_true",
            help="tunnel https untouched, do not open it up",
        )
        parser.add_argument(
            "--insecure",
            action="store_true",
            help="do not verify the certificates of real origins",
        )

    def handle(self, *args, **opts):
        binary = mitm.find_mitmdump()
        if not binary:
            raise CommandError("mitmdump not found: " + mitm.HINT)
        manager = serving.make_server("127.0.0.1", 0, get_wsgi_application())
        threading.Thread(target=manager.serve_forever, daemon=True).start()
        PUBLIC["port"] = opts["port"]
        cmd = mitm.command(
            binary,
            opts["host"],
            opts["port"],
            f"http://127.0.0.1:{manager.server_address[1]}",
            CA_DIR,
            intercept=not opts["no_mitm"],
            insecure=opts["insecure"] or bool(os.environ.get("MOCK_INSECURE")),
        )
        print(
            f"mock proxy on http://{opts['host']}:{opts['port']} "
            f"({binary}, rule manager on :{manager.server_address[1]})",
            flush=True,
        )
        signal.signal(signal.SIGTERM, stop)
        proc = mitm.start(cmd)
        try:
            proc.wait()
        except KeyboardInterrupt:
            pass
        finally:
            if proc.poll() is None:
                proc.terminate()
                proc.wait()
        if proc.returncode not in (0, -15, 130):
            raise CommandError(f"mitmdump stopped with exit code {proc.returncode}")
