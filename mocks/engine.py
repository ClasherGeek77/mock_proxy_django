"""Rule engine — stdlib port of the mitmproxy rules.py addon, framework-free (the only
Django it touches is the data dir setting).

Rule document (one entry of rules.json):
    {"rule-name": "x", "active": true, "priority": 10,
     "match": {"url": "...", "urlContains": "...", "method": "GET",
               "headers": {"K": "v"}, "bodyContains": ["a", "b"]},
     "disconnect": false, "delayMs": 0, "proxyTo": "http://127.0.0.1:40000",
     "requestOverride": {"url", "method", "headersReplace", "headersRemove",
                         "bodyReplace" (dot-path), "bodySet", "rawBodyReplace"},
     "responseOverride": {"status", "headersReplace", "bodySet", "bodyHTML"}}

Semantics kept from the original:
    - lowest priority number wins, inactive and soft-deleted rules never match
    - disconnect closes the socket without a reply
    - delayMs sleeps once, in the request phase only
    - responseOverride answers synthetically, the request never reaches an upstream
    - {host} in any rule string becomes 127.0.0.1
    - rules.json is re-read only when its mtime/size changes (the 2 s live reload,
      no thread)
"""

import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urlparse

from django.conf import settings

# where the mutable state lives (rules.json, rule_content/, hits.jsonl, history.json);
# settings.MOCK_DATA_DIR defaults to the project folder, the MOCK_DATA_DIR variable
# moves it so test runs never dirty the checked-in seed rules
DATA_DIR = str(settings.MOCK_DATA_DIR)
os.makedirs(DATA_DIR, exist_ok=True)
RULES_FILE = os.path.join(DATA_DIR, "rules.json")
CONTENT_DIR = os.path.join(DATA_DIR, "rule_content")
HITS_FILE = os.path.join(DATA_DIR, "hits.jsonl")
MAX_DELAY_MS = 30000

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".json": "application/json",
    ".txt": "text/plain; charset=utf-8",
    ".xml": "application/xml",
}


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def atomic_write(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


# ---------------------------------------------------------------- request helpers
def make_req(method, path, headers, body=""):
    return {
        "method": method.upper(),
        "path": path,
        "headers": dict(headers),
        "body": body,
    }


def hget(headers, name):
    low = name.lower()
    for key, val in headers.items():
        if key.lower() == low:
            return val
    return None


def hset(headers, name, value):
    hdel(headers, name)
    headers[name] = value


def hdel(headers, name):
    low = name.lower()
    for key in [k for k in headers if k.lower() == low]:
        del headers[key]


def req_url(req):
    """host + path, with a canonical http:// in front even for https requests."""
    host = hget(req["headers"], "Host") or "127.0.0.1"
    return f"http://{host}{req['path']}"


def bare(url):
    """A match string without its scheme, so https://x/y and http://x/y both work."""
    return re.sub(r"^https?://", "", url)


def req_from_url(method, url, headers=None, body=""):
    """Build a request dict from a full URL (tester input)."""
    parts = urlparse(url)
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    hdrs = dict(headers or {})
    if parts.netloc and hget(hdrs, "Host") is None:
        hdrs["Host"] = parts.netloc
    return make_req(method or "GET", path, hdrs, body)


# ---------------------------------------------------------------- store
class RuleStore:
    """rules.json with mtime-based reload and atomic writes."""

    def __init__(self, path=RULES_FILE):
        self.path = path
        self.lock = threading.RLock()
        self._sig = None
        self._rules = []

    def _signature(self):
        try:
            st = os.stat(self.path)
            return (st.st_mtime_ns, st.st_size)
        except OSError:
            return None

    def rules(self):
        with self.lock:
            sig = self._signature()
            if sig != self._sig:
                self._rules = self._read()
                self._sig = sig
            return list(self._rules)

    def _read(self):
        try:
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return (
                self._rules
            )  # keep last good set when the file is missing or half-written
        return data if isinstance(data, list) else self._rules

    def save_all(self, rules):
        with self.lock:
            atomic_write(self.path, json.dumps(rules, indent=2) + "\n")
            self._sig = None  # force re-read, picks up the new mtime


# ---------------------------------------------------------------- metrics
class Metrics:
    def __init__(self, journal=HITS_FILE):
        self.journal = journal
        self.lock = threading.Lock()
        self.reset(remove_journal=False)

    def reset(self, remove_journal=True):
        with self.lock:
            self.total = 0
            self.by_status = {}
            self.by_rule = {}
            self.started = now_iso()
        if remove_journal:
            try:
                os.remove(self.journal)
            except OSError:
                pass

    def request(self, status):
        with self.lock:
            self.total += 1
            self.by_status[str(status)] = self.by_status.get(str(status), 0) + 1

    def hit(self, rule_name, action, method, url):
        with self.lock:
            row = self.by_rule.setdefault(
                rule_name, {"hits": 0, "actions": {}, "last": None}
            )
            row["hits"] += 1
            row["actions"][action] = row["actions"].get(action, 0) + 1
            row["last"] = now_iso()
            try:
                with open(self.journal, "a", encoding="utf-8") as fh:
                    fh.write(
                        json.dumps(
                            {
                                "ts": row["last"],
                                "rule": rule_name,
                                "action": action,
                                "method": method,
                                "url": url,
                            }
                        )
                        + "\n"
                    )
            except OSError:
                pass

    def snapshot(self):
        with self.lock:
            return {
                "total": self.total,
                "byStatus": dict(self.by_status),
                "byRule": json.loads(json.dumps(self.by_rule)),
                "since": self.started,
            }


# ---------------------------------------------------------------- matching
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


def set_json_path(obj, path, value):
    keys = path.split(".")
    for key in keys[:-1]:
        obj = obj.setdefault(key, {})
    obj[keys[-1]] = value


def macro(rule):
    return json.loads(json.dumps(rule).replace("{host}", "127.0.0.1"))


def action_of(rule):
    if rule.get("disconnect"):
        return "disconnect"
    if rule.get("responseOverride"):
        return "synthetic-response"
    if rule.get("proxyTo"):
        return "proxy"
    if rule.get("requestOverride"):
        return "modify-request"
    if rule.get("delayMs", 0) > 0:
        return "delay"
    return "match"


def apply_request_override(req, over):
    req = {
        "method": req["method"],
        "path": req["path"],
        "headers": dict(req["headers"]),
        "body": req["body"],
    }
    if over.get("url"):
        parts = urlparse(over["url"])
        req["path"] = (parts.path or "/") + ("?" + parts.query if parts.query else "")
    if over.get("method"):
        req["method"] = over["method"].upper()
    for key, val in (over.get("headersReplace") or {}).items():
        hset(req["headers"], key, val)
    for key in over.get("headersRemove") or []:
        hdel(req["headers"], key)
    if over.get("bodyReplace"):
        try:
            body = json.loads(req["body"])
            for path, val in over["bodyReplace"].items():
                set_json_path(body, path, val)
            req["body"] = json.dumps(body)
        except (ValueError, AttributeError, TypeError):
            pass  # same as the original: a body that is not json is left alone
    if over.get("bodySet") is not None:
        bs = over["bodySet"]
        req["body"] = bs if isinstance(bs, str) else json.dumps(bs)
    if over.get("rawBodyReplace"):
        req["body"] = over["rawBodyReplace"]
    return req


# ---------------------------------------------------------------- content
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


def synth_response(over):
    status = int(over.get("status", 200))
    headers = dict(over.get("headersReplace") or {})
    ctype = None
    if over.get("bodyHTML"):
        body, ctype = fetch_body(over["bodyHTML"])
    elif over.get("bodySet") is not None:
        bs = over["bodySet"]
        if isinstance(bs, str):
            body = bs.encode("utf-8")
        else:
            body = json.dumps(bs).encode("utf-8")
            ctype = "application/json"
    else:
        body = b""
    if ctype and hget(headers, "Content-Type") is None:
        headers["Content-Type"] = ctype
    return status, headers, body


def forward(req, base):
    """proxyTo: replay the (possibly overridden) request against another origin."""
    if urlparse(base).scheme not in ("http", "https"):
        err = {"error": "proxy failed", "detail": "proxyTo must be an http(s) url"}
        return 502, {"Content-Type": "application/json"}, json.dumps(err).encode()
    skip = {"host", "content-length", "connection", "accept-encoding"}
    hdrs = {k: v for k, v in req["headers"].items() if k.lower() not in skip}
    data = req["body"].encode("utf-8") if req["body"] else None
    call = urllib.request.Request(
        base.rstrip("/") + req["path"], data=data, headers=hdrs, method=req["method"]
    )
    try:
        # scheme is checked above: http(s) only, never file:/ or custom
        with urllib.request.urlopen(call, timeout=5) as resp:  # nosec B310
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()
    except (urllib.error.URLError, OSError) as exc:
        return (
            502,
            {"Content-Type": "application/json"},
            json.dumps({"error": "proxy failed", "detail": str(exc)}).encode(),
        )


# ---------------------------------------------------------------- engine
class Engine:
    def __init__(self, store=None, metrics=None):
        self.store = store or RuleStore()
        self.metrics = metrics or Metrics()
        self.paused = False

    def candidates(self, req):
        found = [r for r in self.store.rules() if match_rule(req, r)]
        return sorted(
            found, key=lambda r: r.get("priority", 999)
        )  # stable: ties keep file order

    def pick(self, req):
        found = self.candidates(req)
        return found[0] if found else None

    def explain(self, req):
        """Dry run for the tester: what would happen, with zero side effects."""
        found = self.candidates(req)
        out = {
            "paused": self.paused,
            "matched": bool(found),
            "rule": None,
            "action": "none",
            "delayMs": 0,
            "candidates": [r.get("rule-name") for r in found],
        }
        if found:
            rule = macro(found[0])
            out.update(
                {
                    "rule": rule.get("rule-name"),
                    "priority": rule.get("priority", 999),
                    "action": action_of(rule),
                    "delayMs": min(int(rule.get("delayMs", 0) or 0), MAX_DELAY_MS),
                }
            )
        return out

    def apply(self, req):
        """Run the winning rule.

        Returns {kind: none|disconnect|synthetic|forward, req, rule, response?,
        proxyTo?}.
        """
        rule = self.pick(req)
        if not rule:
            return {"kind": "none", "req": req, "rule": None}
        rule = macro(rule)
        name = rule.get("rule-name")
        url = req_url(req)
        if rule.get("disconnect"):
            self.metrics.hit(name, "disconnect", req["method"], url)
            return {"kind": "disconnect", "req": req, "rule": name}
        delay = min(int(rule.get("delayMs", 0) or 0), MAX_DELAY_MS)
        if delay > 0:
            time.sleep(delay / 1000.0)
        over = rule.get("requestOverride")
        if over:
            req = apply_request_override(req, over)
        action = action_of(rule)
        self.metrics.hit(name, action, req["method"], url)
        if rule.get("responseOverride"):
            return {
                "kind": "synthetic",
                "req": req,
                "rule": name,
                "response": synth_response(rule["responseOverride"]),
            }
        if rule.get("proxyTo"):
            return {
                "kind": "forward",
                "req": req,
                "rule": name,
                "proxyTo": rule["proxyTo"],
            }
        return {"kind": "none", "req": req, "rule": name}
