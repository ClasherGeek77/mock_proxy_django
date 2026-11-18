"""The process-wide singletons: one engine (rules, metrics, pause switch), one admin
facade over it, one local CA."""

import os

from . import admin, engine, tlsca

VERSION = "1.0.0"
ENGINE = engine.Engine()
ADMIN = admin.Admin(ENGINE)
CA = tlsca.CA(os.path.join(engine.DATA_DIR, "ca"))
