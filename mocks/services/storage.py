"""rules.json with mtime-based reload and atomic writes, and the request metrics."""

import json
import os
import threading
from datetime import datetime, timezone

from ..conf import HITS_FILE, RULES_FILE


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def atomic_write(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


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
