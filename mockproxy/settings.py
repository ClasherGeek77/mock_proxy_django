"""Settings: no database, no sessions, no templates, no auth. Django is the url
router, the request/response objects and the WSGI plumbing of a rule-driven mock."""

import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
# rules.json, rule_content/, hits.jsonl, history.json and ca/ live here; the
# MOCK_DATA_DIR variable moves them off the checked-in seed rules (the tests do)
MOCK_DATA_DIR = Path(os.environ.get("MOCK_DATA_DIR") or BASE_DIR)

DEBUG = False
ALLOWED_HOSTS = ["*"]  # a proxy is asked for every host on earth
SECRET_KEY = secrets.token_hex(32)  # nothing is signed, so nothing to keep
INSTALLED_APPS = ["mocks"]
MIDDLEWARE = ["mocks.middleware.MockMiddleware"]
ROOT_URLCONF = "mockproxy.urls"
WSGI_APPLICATION = "mockproxy.wsgi.application"
DATABASES = {}
USE_TZ = True
DATA_UPLOAD_MAX_MEMORY_SIZE = None  # a mocked body can be any size
DEFAULT_AUTO_FIELD = "django.db.models.AutoField"
