"""Live browser e2e: drives /ui in headless Chrome like a person would, and verifies
every effect with an independent HTTP call. Run it through ./run_e2e.sh."""

import json
import os
import sys
import time
import urllib.error
import urllib.request

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait

BASE = os.environ["MOCK_URL"].rstrip("/")
TMP = os.environ.get("E2E_TMP", "/tmp")
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
PATH = "/e2e-ui"


def hit(path, method="GET"):
    start = time.perf_counter()
    try:
        res = OPENER.open(urllib.request.Request(BASE + path, method=method), timeout=5)
        return res.status, res.read().decode(), time.perf_counter() - start
    except urllib.error.HTTPError as err:
        return err.code, err.read().decode(), time.perf_counter() - start
    except (urllib.error.URLError, ConnectionError, OSError):
        return None, "", time.perf_counter() - start


opts = Options()
opts.binary_location = os.environ.get(
    "CHROME_BIN", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
)
for arg in ("--headless=new", "--no-sandbox", "--window-size=1400,1000"):
    opts.add_argument(arg)
opts.add_argument("--no-proxy-server")
opts.set_capability("goog:loggingPrefs", {"browser": "ALL"})
d = webdriver.Chrome(service=Service(os.environ["CHROMEDRIVER_BIN"]), options=opts)
wait = WebDriverWait(d, 8)
results = []


def check(label, cond, extra=""):
    results.append(bool(cond))
    print(
        ("PASS " if cond else "FAIL ") + label + ("" if cond else " -> " + str(extra))
    )


def by(id_):
    return d.find_element(By.ID, id_)


def type_into(id_, text):
    el = by(id_)
    el.clear()
    el.send_keys(text)


def settle(sec=0.6):
    time.sleep(sec)


def cells(name):
    """The text cells of a rule's table row ([] when there is none). The page
    re-renders the table every few seconds, so read it in one go."""
    return d.execute_script(
        "const tr = [...document.querySelectorAll('#rules tr')].find("
        "r => r.cells[1] && r.cells[1].textContent === arguments[0]);"
        "return tr ? [...tr.cells].map(c => c.textContent) : [];",
        name,
    )


def row_click(name, what):
    """what = 'try' | 'edit' | 'delete' | 'on' (the checkbox)."""
    d.execute_script(
        "const tr = [...document.querySelectorAll('#rules tr')].find("
        "r => r.cells[1] && r.cells[1].textContent === arguments[0]);"
        "const w = arguments[1];"
        "(w === 'on' ? tr.querySelector('input') : "
        "[...tr.querySelectorAll('button')].find(b => b.textContent === w)).click();",
        name,
        what,
    )


def alert_text(accept):
    alert = d.switch_to.alert
    text = alert.text
    alert.accept() if accept else alert.dismiss()
    return text


def pick_mode(value):
    d.find_element(By.CSS_SELECTOR, f"input[name=mode][value={value}]").click()


def fill_rule(url, status=None, body=None, opened=False):
    if not opened:
        by("new").click()
    type_into("url", url)
    if status:
        type_into("status", str(status))
    if body is not None:
        type_into("body", body)


def save():
    d.find_element(By.CSS_SELECTOR, "#form button[type=submit]").click()
    settle()


def api(method, path, doc=None):
    data = json.dumps(doc).encode() if doc is not None else None
    req = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with OPENER.open(req, timeout=5) as res:
            return res.status, json.loads(res.read() or "null")
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read() or "null")


try:
    d.get(BASE + "/ui")
    wait.until(lambda x: len(d.find_elements(By.CSS_SELECTOR, "#rules tr")) >= 5)

    # 1. plain html
    check("loads with the 5 seed rules", cells("yahoo-search-limited") != [], d.title)
    check("title says mock proxy", d.title == "mock proxy", d.title)
    check(
        "one self-contained file: no external stylesheet or script",
        d.execute_script(
            "return document.querySelectorAll('link[rel=stylesheet], script[src]').length === 0"
        ),
    )
    check(
        "proxy hint shows a copyable curl line",
        "curl -x " + BASE in by("hint").text,
        by("hint").text,
    )
    check(
        "rule row says what it does",
        "answer 429" in " ".join(cells("yahoo-search-limited")),
    )
    check("dialog is closed until asked", not by("dlg").is_displayed())

    # 2. create a rule with the form
    by("new").click()
    check("dialog opens", by("dlg").is_displayed())
    check(
        "cursor starts in the url field",
        d.execute_script("return document.activeElement.id") == "url",
    )
    fill_rule(PATH, status=500, body='{"error": "boom"}', opened=True)
    check("status accepts a typed code", by("status").get_attribute("value") == "500")
    check("nothing is live before save", hit(PATH)[0] == 404, hit(PATH)[0])
    save()
    status, text, _ = hit(PATH)
    check("save makes it live", status == 500 and "boom" in text, (status, text))
    check("message says so", "live now" in by("msg").text, by("msg").text)
    check("name was made from the url", "e2e-ui" in " ".join(cells("e2e-ui")))
    check("dialog closes after save", not by("dlg").is_displayed())
    out = by("t-out").text
    check(
        "save proves the rule right away in the try-it box",
        out.startswith("500") and "boom" in out and "e2e-ui" in by("t-rule").text,
        (out, by("t-rule").text),
    )

    # 3. edit
    row_click("e2e-ui", "edit")
    check("edit opens the filled form", by("url").get_attribute("value") == PATH)
    check("name cannot change when editing", not by("name").is_enabled())
    type_into("status", "207")
    save()
    check("edited rule is live", hit(PATH)[0] == 207, hit(PATH)[0])

    # 4. on / off
    row_click("e2e-ui", "on")
    settle()
    check("switch off -> 404", hit(PATH)[0] == 404, hit(PATH)[0])
    row_click("e2e-ui", "on")
    settle()
    check("switch on -> answers again", hit(PATH)[0] == 207, hit(PATH)[0])

    # 5. try it, with the winner named
    row_click("e2e-ui", "try")
    settle()
    check(
        "row try button sends the rule's own path",
        by("t-path").get_attribute("value").endswith(PATH)
        and "207" in by("t-out").text,
        (by("t-path").get_attribute("value"), by("t-out").text),
    )
    type_into("t-path", PATH)
    d.find_element(By.CSS_SELECTOR, "#try button").click()
    settle()
    out = by("t-out").text
    check("send shows real status and time", "207" in out and " ms" in out, out)
    check(
        "send names the winning rule", "e2e-ui" in by("t-rule").text, by("t-rule").text
    )
    check(
        "hit count shows in the table",
        cells("e2e-ui")[5] not in ("0", ""),
        cells("e2e-ui"),
    )

    # 6. hang up and delay
    row_click("e2e-ui", "edit")
    pick_mode("hangup")
    save()
    check("hang up: a real client gets no reply", hit(PATH)[0] is None)
    d.find_element(By.CSS_SELECTOR, "#try button").click()
    settle(1)
    check(
        "send explains the missing reply",
        "no reply" in by("t-out").text.lower(),
        by("t-out").text,
    )
    row_click("e2e-ui", "edit")
    pick_mode("respond")
    type_into("status", "207")
    type_into("delay", "400")
    save()
    status, _, took = hit(PATH)
    check(
        "delay: answer arrives after the wait",
        status == 207 and took >= 0.4,
        (status, took),
    )

    # 7. guards: overwrite, empty form
    fill_rule(PATH, status=200)
    type_into("name", "e2e-ui")
    d.find_element(By.CSS_SELECTOR, "#form button[type=submit]").click()
    settle(0.3)
    asked = alert_text(accept=False)
    check("saving over an existing name asks first", "already exists" in asked, asked)
    check("the existing rule was left alone", hit(PATH)[0] == 207, hit(PATH)[0])
    check("dialog stays open after declining", by("dlg").is_displayed())
    d.find_element(By.ID, "cancel").click()
    check("cancel closes the dialog", not by("dlg").is_displayed())
    by("new").click()
    d.find_element(By.CSS_SELECTOR, "#form button[type=submit]").click()
    settle(0.3)
    check(
        "empty rule is refused next to the field",
        by("dlg").is_displayed() and by("url").get_attribute("validationMessage"),
    )
    by("url").send_keys(Keys.ESCAPE)
    settle(0.3)
    check("escape closes the dialog", not by("dlg").is_displayed())

    # 8. fields the form does not show survive an edit
    api(
        "PUT",
        "/api/rules/e2e-keep",
        {
            "priority": 5,
            "match": {"urlContains": "/e2e-keep", "headers": {"X-Mode": "a"}},
            "responseOverride": {"status": 202, "headersReplace": {"X-Seen": "1"}},
        },
    )
    settle(3.2)  # the page polls every 3 s
    row_click("e2e-keep", "edit")
    type_into("status", "203")
    save()
    _, kept = api("GET", "/api/rules/e2e-keep")
    check(
        "header match and response headers survive a form save",
        kept["match"].get("headers") == {"X-Mode": "a"}
        and kept["responseOverride"]["headersReplace"] == {"X-Seen": "1"}
        and kept["responseOverride"]["status"] == 203,
        kept,
    )
    api("DELETE", "/api/rules/e2e-keep")

    # 9. pause
    by("pause").click()
    settle()
    check("pause: mocked path answers 503", hit(PATH)[0] == 503, hit(PATH)[0])
    check("pause is shown", "PAUSED" in by("state").text, by("state").text)
    by("pause").click()
    settle()
    check("resume works", hit(PATH)[0] == 207 and by("state").text == "on")

    # 10. delete
    row_click("e2e-ui", "delete")
    asked = alert_text(accept=False)
    check("delete asks first", "Delete" in asked, asked)
    check("dismissing keeps the rule", cells("e2e-ui") != [] and hit(PATH)[0] == 207)
    row_click("e2e-ui", "delete")
    alert_text(accept=True)
    settle()
    check(
        "deleted rule is gone: 404 and no row",
        hit(PATH)[0] == 404 and cells("e2e-ui") == [],
    )

    # 11. a real site url goes through the proxy and a seed rule answers it
    type_into("t-path", "www.yahoo.com/mail")
    d.find_element(By.CSS_SELECTOR, "#try button").click()
    settle()
    check(
        "try it with a site url is mocked by the seed rule",
        by("t-out").text.startswith("503") and "yahoo-mail-down" in by("t-rule").text,
        (by("t-out").text, by("t-rule").text),
    )
    type_into("t-path", "www.yahoo.com/finance")
    d.find_element(By.CSS_SELECTOR, "#try button").click()
    settle(1)
    check(
        "hang-up seed rule shows no reply for a site url",
        "No reply" in by("t-out").text,
        by("t-out").text,
    )

    type_into("t-path", "https://www.yahoo.com/mail")
    d.find_element(By.CSS_SELECTOR, "#try button").click()
    settle()
    check(
        "an https url is mocked too",
        by("t-out").text.startswith("503") and "yahoo-mail-down" in by("t-rule").text,
        (by("t-out").text, by("t-rule").text),
    )
    check(
        "page offers the CA certificate and an https curl line",
        by("hint-s").text.startswith("curl -k -x")
        and d.find_element(By.CSS_SELECTOR, "a[href='/ca.pem']").is_displayed(),
    )

    # 12. a path nobody mocks is a plain 404 now
    type_into("t-path", "/nothing-here")
    d.find_element(By.CSS_SELECTOR, "#try button").click()
    settle()
    check(
        "no-rule path on this server is a 404",
        by("t-out").text.startswith("404") and "No rule matches" in by("t-rule").text,
        by("t-out").text,
    )

    severe = [log for log in d.get_log("browser") if log["level"] == "SEVERE"]
    ok_noise = ("ERR_EMPTY_RESPONSE", "ERR_CONNECTION", "Failed to fetch", "status of")
    unexpected = [
        log for log in severe if not any(noise in log["message"] for noise in ok_noise)
    ]
    check("no unexpected console errors", not unexpected, unexpected)
finally:
    d.quit()
print("\n%d/%d passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
