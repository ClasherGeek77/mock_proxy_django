"""WSGI entry point. Under any WSGI server the admin api, the ui and direct mocking
work; the proxy itself needs `manage.py runmock`, which starts mitmdump in front."""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")
application = get_wsgi_application()
