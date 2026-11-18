"""Where the mutable state lives and the few fixed numbers. The data directory is
settings.MOCK_DATA_DIR (data/ by default); the MOCK_DATA_DIR variable moves it so test
runs never dirty the checked-in seed rules."""

import os

from django.conf import settings

VERSION = "1.0.0"
DATA_DIR = str(settings.MOCK_DATA_DIR)
os.makedirs(DATA_DIR, exist_ok=True)
RULES_FILE = os.path.join(DATA_DIR, "rules.json")
CONTENT_DIR = os.path.join(DATA_DIR, "rule_content")
HITS_FILE = os.path.join(DATA_DIR, "hits.jsonl")
HISTORY_FILE = os.path.join(DATA_DIR, "history.json")
CA_DIR = os.path.join(DATA_DIR, "ca")  # mitmdump's --set confdir
CA_CERT = os.path.join(CA_DIR, "mitmproxy-ca-cert.pem")
MAX_DELAY_MS = 30000
