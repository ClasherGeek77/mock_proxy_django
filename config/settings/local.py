"""The one environment this tool has: a developer's machine. A mock proxy is never
deployed, so there is no production module."""

import os
import secrets
from pathlib import Path

from .base import *  # pylint: disable=wildcard-import,unused-wildcard-import

ALLOWED_HOSTS = ["*"]  # a proxy is asked for every host on earth
SECRET_KEY = secrets.token_hex(32)  # nothing is signed, so nothing to keep
# rules.json, rule_content/, hits.jsonl, history.json and ca/ live here; the
# MOCK_DATA_DIR variable moves them off the checked-in seed rules (the tests do)
MOCK_DATA_DIR = Path(os.environ.get("MOCK_DATA_DIR") or BASE_DIR / "data")
