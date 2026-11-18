"""Does a rule match a request."""

from .messages import bare, hget, req_url


def match_rule(req, rule):
    if rule.get("active", True) is False or rule.get("deletedAt"):
        return False
    m = rule.get("match") or {}
    if not m:
        return False
    full = req_url(req)
    if m.get("url") and bare(m["url"]) not in (bare(full), req["path"]):
        return False
    if m.get("urlContains") and bare(m["urlContains"]) not in bare(full):
        return False
    if m.get("method") and m["method"].upper() != req["method"]:
        return False
    for key, val in (m.get("headers") or {}).items():
        if hget(req["headers"], key) != val:
            return False
    parts = m.get("bodyContains") or []
    if isinstance(parts, str):
        parts = [parts]
    for part in parts:
        if part not in req["body"]:
            return False
    return True
