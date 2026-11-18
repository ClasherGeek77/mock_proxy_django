"""The rule engine: pick the winning rule for a request and run it. A port of the
mitmproxy rules.py addon, framework-free.

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

import time

from ..conf import MAX_DELAY_MS
from .actions import action_of, apply_request_override, macro, synth_response
from .matching import match_rule
from .messages import req_url
from .storage import Metrics, RuleStore


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
