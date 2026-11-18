"""The process-wide singletons: one engine (rules, metrics, pause switch), one admin
facade over it, and where mitmdump keeps its CA."""

import os

from . import admin, engine

VERSION = "1.0.0"
ENGINE = engine.Engine()
ADMIN = admin.Admin(ENGINE)
CA_DIR = os.path.join(engine.DATA_DIR, "ca")  # mitmdump's --set confdir
CA_CERT = os.path.join(CA_DIR, "mitmproxy-ca-cert.pem")
PUBLIC = {"port": None}  # the port mitmdump listens on, set by runmock
