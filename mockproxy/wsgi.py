"""WSGI entry point. Under any WSGI server the admin api, the ui and direct mocking
work; proxy mode and https interception need `manage.py runmock`, which owns the
socket."""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mockproxy.settings")
application = get_wsgi_application()
