"""Settings every run shares: no database, no sessions, no templates, no auth. Django
is the url router, the request/response objects and the WSGI plumbing of a
rule-driven mock. What differs per machine lives in local.py."""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent

DEBUG = False
INSTALLED_APPS = ["mocks"]
MIDDLEWARE = ["mocks.middleware.MockMiddleware"]
ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
DATABASES = {}
USE_TZ = True
DATA_UPLOAD_MAX_MEMORY_SIZE = None  # a mocked body can be any size
DEFAULT_AUTO_FIELD = "django.db.models.AutoField"
