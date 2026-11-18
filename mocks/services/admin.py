"""Admin domain: rule validation, save/delete/toggle/import, history snapshots, the
tester and rule-content storage. The routes live in urls.py, the http shape in apis/;
every method here returns (status, payload).

Save validation: hard errors answer 400. Soft warnings come back in "warnings"; with
?strict=1 they become errors too.
"""

import json
import os
import re
import uuid

from .. import conf
from . import messages, storage


HISTORY_CAP = 10


RESERVED = {"export", "import", "test"}


KNOWN_KEYS = {
    "rule-name",
    "active",
    "priority",
    "match",
    "disconnect",
    "delayMs",
    "proxyTo",
    "requestOverride",
    "responseOverride",
    "deletedAt",
    "updatedAt",
    "description",
}


NAME_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def norm_name(name):
    name = (name or "").strip()
    return name[:-5] if name.endswith(".json") else name


def validate(doc):
    errors, warnings = [], []
    if not isinstance(doc, dict):
        return ["rule must be a json object"], []
    name = norm_name(doc.get("rule-name"))
    if not name:
        errors.append("rule-name is required")
    elif not NAME_OK.match(name) or name in RESERVED:
        errors.append(
            f"rule-name must match [A-Za-z0-9._-] and not be one of {sorted(RESERVED)}"
        )
    if "priority" in doc and (
        not isinstance(doc["priority"], int) or isinstance(doc["priority"], bool)
    ):
        errors.append("priority must be an integer")
    for key in ("match", "requestOverride", "responseOverride"):
        if key in doc and not isinstance(doc[key], dict):
            errors.append(f"{key} must be an object")
    if errors:
        return errors, warnings
    if not doc.get("match"):
        warnings.append("empty match: the rule can never fire")
    if not (
        doc.get("disconnect")
        or doc.get("delayMs")
        or doc.get("proxyTo")
        or doc.get("requestOverride")
        or doc.get("responseOverride")
    ):
        warnings.append(
            "no action (disconnect/delayMs/proxyTo/requestOverride/responseOverride)"
        )
    delay = doc.get("delayMs", 0)
    if not isinstance(delay, (int, float)) or delay < 0 or delay > conf.MAX_DELAY_MS:
        warnings.append(f"delayMs outside 0..{conf.MAX_DELAY_MS} (it is clamped)")
    status = (doc.get("responseOverride") or {}).get("status", 200)
    if not isinstance(status, int) or not 100 <= status <= 599:
        warnings.append("responseOverride.status should be an integer 100..599")
    unknown = sorted(set(doc) - KNOWN_KEYS)
    if unknown:
        names = ", ".join(unknown)
        warnings.append(f"unknown keys ignored by the engine: {names}")
    return errors, warnings


class Admin:
    def __init__(self, eng):
        self.eng = eng
        self.store = eng.store

    # ------------------------------------------------------------ history
    def history_of(self):
        try:
            with open(conf.HISTORY_FILE, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return {}

    def _snapshot(self, doc):
        hist = self.history_of()
        rows = hist.setdefault(doc["rule-name"], [])
        rows.insert(
            0, {"id": uuid.uuid4().hex[:8], "ts": storage.now_iso(), "doc": doc}
        )
        del rows[HISTORY_CAP:]
        storage.atomic_write(conf.HISTORY_FILE, json.dumps(hist, indent=2) + "\n")

    # ------------------------------------------------------------ rule store ops
    @staticmethod
    def find(rules, name):
        for idx, rule in enumerate(rules):
            if rule.get("rule-name") == name:
                return idx
        return -1

    def live(self):
        return [r for r in self.store.rules() if not r.get("deletedAt")]

    def _save(self, doc):
        """Insert or replace one doc (snapshotting the old one). Returns created?"""
        with self.store.lock:
            rules = self.store.rules()
            doc = dict(doc)
            doc["rule-name"] = norm_name(doc["rule-name"])
            doc.pop("deletedAt", None)
            doc["updatedAt"] = storage.now_iso()
            idx = self.find(rules, doc["rule-name"])
            if idx >= 0:
                self._snapshot(rules[idx])
                rules[idx] = doc
            else:
                rules.append(doc)
            self.store.save_all(rules)
            return idx < 0

    def save(self, doc, strict):
        errors, warnings = validate(doc)
        if strict:
            errors, warnings = errors + warnings, []
        if errors:
            return 400, {"success": False, "errors": errors}
        created = self._save(doc)
        return (
            201 if created else 200,
            {
                "success": True,
                "name": norm_name(doc["rule-name"]),
                "warnings": warnings,
            },
        )

    def delete(self, name):
        with self.store.lock:
            rules = self.store.rules()
            idx = self.find(rules, name)
            if idx < 0 or rules[idx].get("deletedAt"):
                return 404, {"error": "no such rule"}
            self._snapshot(rules[idx])
            rules[idx] = dict(rules[idx], deletedAt=storage.now_iso())
            self.store.save_all(rules)
        return 200, {"success": True, "name": name}

    def toggle(self, name):
        with self.store.lock:
            rules = self.store.rules()
            idx = self.find(rules, name)
            if idx < 0 or rules[idx].get("deletedAt"):
                return 404, {"error": "no such rule"}
            rules[idx] = dict(
                rules[idx],
                active=not rules[idx].get("active", True),
                updatedAt=storage.now_iso(),
            )
            self.store.save_all(rules)
            return 200, {"success": True, "name": name, "active": rules[idx]["active"]}

    def import_rules(self, data, strict):
        docs = data.get("rules") if isinstance(data, dict) else data
        if not isinstance(docs, list):
            return 400, {"success": False, "errors": ["body must be an array of rules"]}
        count, errors = 0, []
        for doc in docs:
            errs, warns = validate(doc)
            if strict:
                errs, warns = errs + warns, []
            if errs:
                label = doc.get("rule-name") if isinstance(doc, dict) else None
                errors.append({"name": label, "errors": errs})
                continue
            self._save(doc)
            count += 1
        return 200, {
            "success": not errors,
            "count": count,
            "skipped": len(errors),
            "errors": errors,
        }

    def test(self, data):
        if not isinstance(data, dict) or not (data.get("url") or data.get("path")):
            return 400, {"success": False, "errors": ["url is required"]}
        url = data.get("url") or "http://127.0.0.1" + data["path"]
        req = messages.req_from_url(
            data.get("method") or "GET",
            url,
            data.get("headers"),
            data.get("body") or "",
        )
        return 200, self.eng.explain(req)

    def restore(self, ident):
        for name, rows in self.history_of().items():
            for row in rows:
                if row["id"] == ident:
                    with self.store.lock:
                        current = self.store.rules()
                        idx = self.find(current, name)
                        if idx >= 0:
                            self._snapshot(current[idx])  # restore snapshots first
                            current[idx] = row["doc"]
                        else:
                            current.append(row["doc"])
                        self.store.save_all(current)
                    return 200, {"success": True, "name": name, "restored": row["id"]}
        return 404, {"error": "no such snapshot"}

    # ------------------------------------------------------------ rule content
    @staticmethod
    def content_names():
        os.makedirs(conf.CONTENT_DIR, exist_ok=True)
        return sorted(os.listdir(conf.CONTENT_DIR))

    @staticmethod
    def content_put(name, body):
        os.makedirs(conf.CONTENT_DIR, exist_ok=True)
        path = os.path.join(conf.CONTENT_DIR, name)
        existed = os.path.isfile(path)
        storage.atomic_write(path, body)
        return (200 if existed else 201), {"success": True, "name": name}

    @staticmethod
    def content_delete(name):
        path = os.path.join(conf.CONTENT_DIR, name)
        if not os.path.isfile(path):
            return 404, {"error": "no such content"}
        os.remove(path)
        return 200, {"success": True}
