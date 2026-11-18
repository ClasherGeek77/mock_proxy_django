"""Stored rule content (rule_content/) and the bodyHTML references that point at it."""

import os
import urllib.error
import urllib.request
from urllib.parse import urlparse

from ..conf import CONTENT_DIR


CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".json": "application/json",
    ".txt": "text/plain; charset=utf-8",
    ".xml": "application/xml",
}


def content_path(name):
    """Resolve a stored rule-content name inside rule_content/.

    Extension-less names try the known extensions.
    """
    base = os.path.basename(name)
    if not base or base.startswith("."):
        return None
    full = os.path.join(CONTENT_DIR, base)
    if os.path.isfile(full):
        return full
    if not os.path.splitext(base)[1]:
        for ext in CONTENT_TYPES:
            if os.path.isfile(full + ext):
                return full + ext
    return None


def content_type_of(path):
    return CONTENT_TYPES.get(
        os.path.splitext(path)[1].lower(), "application/octet-stream"
    )


def read_content(name):
    path = content_path(name)
    if not path:
        return None
    with open(path, "rb") as fh:
        return fh.read(), content_type_of(path)


def fetch_body(ref):
    """bodyHTML reference: stored name, /rule-content/<name> url, or any http(s) url."""
    ref = ref.replace("{host}", "127.0.0.1")
    parts = urlparse(ref)
    if parts.path.startswith("/rule-content/"):
        found = read_content(parts.path[len("/rule-content/") :])
    elif parts.scheme in ("http", "https"):
        try:
            # scheme is checked two lines up: http(s) only, never file:/ or custom
            with urllib.request.urlopen(ref, timeout=2) as resp:  # nosec B310
                found = (resp.read(), resp.headers.get("Content-Type", "text/html"))
        except (urllib.error.URLError, OSError, ValueError) as exc:
            return (
                f"<html><body>Error loading remote content: {exc}</body></html>"
            ).encode(), "text/html"
    else:
        found = read_content(ref)
    if found is None:
        return (
            b"<html><body>Error loading content: not found</body></html>",
            "text/html",
        )
    return found
