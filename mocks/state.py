"""The process-wide singletons: one engine (rules, metrics, pause switch), one admin
facade over it."""

from .services import admin, engine

ENGINE = engine.Engine()
ADMIN = admin.Admin(ENGINE)
PUBLIC = {"port": None}  # the port mitmdump listens on, set by runmock
