# mock_proxy_django

A rule-driven mock proxy. Point a client at it as its HTTP proxy: requests that match a rule get a mocked answer (a fixed status and body, a delay, a dropped connection, a rewritten request), everything else goes through to the real server. It is also a plain mock server for direct calls, with an admin API and an editor UI on the same port. The wire work is done by the real mitmproxy (`mitmdump`); Django is only the rule manager behind it: no database, no sessions, no templates.

## when to use it

Use it when you need to make a real client (an app, a script, a browser, a test) see a failure or a slow answer from a real host without changing the client: "www.yahoo.com/mail returns 503", "the finance page hangs up", "search is rate limited". It also fits when you want to learn how a mocking proxy is put together.

Do not use it if:

- you only need a fake API to call directly: use https://github.com/ClasherGeek77/reqresin_clone (a local reqres.in clone) or https://github.com/ClasherGeek77/saucedemo_clone
- you want to send requests and look at the answers by hand: use https://github.com/ClasherGeek77/postman_collection or https://github.com/ClasherGeek77/bruno_collection
- you need a production service: this is a developer tool, it is never deployed (no production settings exist)

## what you need

| need | detail |
|---|---|
| Python 3.11 | `.python-version` says 3.11.14; mitmproxy needs 3.10+. `scripts/first_setup.sh` looks for `python3.11` on PATH. Download from https://www.python.org/downloads/. |
| network for the first setup | `pip` installs Django 4.2.30, mitmproxy 11.0.2 and the test tools (pytest 7.4.4, pytest-html, requests, black, bandit, pylint) from `requirements/local.txt` |
| curl | for the examples below |
| git | to clone the repo |

Checked on macOS (10.15) with mitmproxy 11.0.2 and Python 3.11.14. Linux: not verified here; nothing in the code is macOS-specific.

`runmock` finds the proxy binary in this order: the `MITMDUMP_BIN` environment variable, `.venv/bin/mitmdump` (installed by `first_setup.sh`), then `mitmdump` on `PATH` (so a system install of mitmproxy also works).

## quick start

```bash
git clone https://github.com/ClasherGeek77/mock_proxy_django.git
cd mock_proxy_django
scripts/first_setup.sh                   # once: builds .venv
.venv/bin/python manage.py runmock       # http://127.0.0.1:38800
```

You should see one line like `mock proxy on http://127.0.0.1:38800 (.../.venv/bin/mitmdump, rule manager on :<port>)`, and from then on one line per request (method, URL, status). Stop it with Ctrl+C; a plain `kill` takes mitmdump down with it.

Options: `--port 9000`, `--host 127.0.0.1`, `--no-mitm` (tunnel https untouched), `--insecure` (do not verify real origins' certificates, also `MOCK_INSECURE=1`).

In a second terminal, use it as a proxy. The seed rules mock some `www.yahoo.com` paths, so this works offline:

```bash
curl -i -x http://127.0.0.1:38800 http://www.yahoo.com/mail
```

You should see `HTTP/1.1 503 Service Unavailable` and the body `{"error": "mail is down"}`. More:

```bash
curl -k -x http://127.0.0.1:38800 https://www.yahoo.com/mail       # https too; -k ignores the mock's certificate; same 503 body
curl -x http://127.0.0.1:38800 http://www.yahoo.com/search         # {"error": "slow down"} with status 429
curl -x http://127.0.0.1:38800 http://www.yahoo.com/finance        # no reply at all: curl reports an empty reply (exit 52)
curl http://127.0.0.1:38800/health                                 # {"status": "ok"}
```

Open http://127.0.0.1:38800/ui in a browser for the rule editor. Without `-x`, a call to the mock's own address is a direct call, so `/api`, `/ui` and `/health` always answer from the mock.

Add a rule over the API and use it at once (no restart):

```bash
curl -X POST http://127.0.0.1:38800/api/rules -H 'Content-Type: application/json' \
  -d '{"rule-name":"yahoo-sports-teapot","priority":5,"match":{"urlContains":"www.yahoo.com/sports"},"responseOverride":{"status":418,"bodySet":{"error":"teapot"}}}'
curl -x http://127.0.0.1:38800 http://www.yahoo.com/sports         # {"error": "teapot"} with status 418
curl -X DELETE http://127.0.0.1:38800/api/rules/yahoo-sports-teapot
```

The server stores rules in `data/rules.json`, and the checked-in file is the seed. Saving or deleting a rule rewrites it, so for experiments start with another data folder and the seed stays clean:

```bash
MOCK_DATA_DIR=/tmp/mock-data .venv/bin/python manage.py runmock
```

(copy `data/rules.json` there first if you want the seed rules.) The folder also holds `hits.jsonl`, the history, rule content and the CA; all of that except the seed is git-ignored.

### run the tests

```bash
scripts/run_tests.sh                       # everything
scripts/run_tests.sh tests/api/test_admin.py   # one file; any pytest arguments pass through
scripts/checks.sh                          # bandit, black, pylint (pylint must be 10/10)
```

You should see `104 passed` (about 15 seconds; two InsecureRequestWarning lines are normal). The suite starts its own server on a free port, with its own data folder, so nothing needs to be running and the seed is not touched. Reports are written to `reports/junit.xml` and `reports/report.html` (git-ignored). `MOCK_URL=http://127.0.0.1:38800 scripts/run_tests.sh` tests an already running server instead (the live-reload test skips because it needs the server's data folder).

## using it as a proxy

```bash
curl -x http://127.0.0.1:38800 http://www.yahoo.com/mail                   # http
curl -k -x http://127.0.0.1:38800 https://www.yahoo.com/mail               # https, ignore the certificate
curl --cacert ca.pem -x http://127.0.0.1:38800 https://www.yahoo.com/mail  # https, trust the mock's CA (fetch it first: curl http://127.0.0.1:38800/ca.pem -o ca.pem)
http_proxy=http://127.0.0.1:38800 ./your-client                            # any client that honours the variable
```

- A request with a full URL in its request line is proxy mode. Rules match the URL as `host/path`: `urlContains` sees `www.yahoo.com/mail`, with or without a leading `http://` or `https://`, so one rule can target one host.
- No rule matches: mitmdump calls the real origin, with the rule's `requestOverride` applied if there was one. An unreachable origin is mitmproxy's own 502 page. Not run against the live yahoo.com here; the test suite covers pass-through with local upstream servers.
- `disconnect`, `delayMs`, `requestOverride`, `responseOverride` and `proxyTo` work the same as for direct calls. A delay stalls that one flow only.
- Pause (`POST /api/mock-state` with `{"paused": true}`) stops mocking but the proxy keeps relaying, so a configured client keeps working.
- A request that names the mock's own address is a direct call, so `/api`, `/ui` and `/health` are never reachable through a proxied foreign host.

### https

mitmdump opens a `CONNECT` tunnel up (man in the middle). Its CA is made on the first start (`ca/mitmproxy-ca-cert.pem` and the key in the data folder, git-ignored) and every host gets a certificate signed by it. The rules then see the https request inside, so `https://www.yahoo.com/mail` is mocked like the http one.

- The client has to trust the CA (`GET /ca.pem`, also linked in the UI) or ignore certificate errors (`curl -k`, `verify=False`, a browser's "proceed"). A client that does neither is refused at the handshake: nothing is mocked and nothing leaks.
- No rule matches: the request goes to the real origin over https and the origin's certificate is verified. `--insecure` (or `MOCK_INSECURE=1`) skips that check for self-signed dev origins.
- `--no-mitm` tunnels https untouched (`--ignore-hosts .*`): the rules only see plain http, and a dead origin is a 502 at the `CONNECT`.
- Certificate-pinning apps refuse the mock's certificate; that is the pin doing its job.
- The CA key signs for any site: keep `ca/` private, delete the folder to make a new CA, and remove the CA from your trust store when you are done.

## why mitmdump in front

A proxy that mocks https is mostly wire work: `CONNECT`, a CA, a certificate per host, TLS on both sides, HTTP/1 and HTTP/2, keep-alive, streaming, the real upstream call. That is what mitmproxy is for, so none of it is rewritten here. The rules engine is a port of the mitmproxy `rules.py` addon.

```
client --> mitmdump :38800 --(addon asks: what do I do with this?)--> django rule manager (loopback, own port)
              |                                                         rules.json, admin api, ui, metrics
              +--> real origin (when the rules leave the request alone)
```

- `mocks/proxy/addon.py` is the mitmproxy addon, one decision per request: **respond** (a mocked response, the origin is never called), **disconnect** (kill the connection, no reply) or **none** (let it through, with the rule's request overrides applied). It speaks to Django over a tiny JSON API (`/api/proxy/decide`, `/api/proxy/seen`).
- A request for the proxy's own port (`/ui`, `/api`, `/health`, a directly mocked path) is not proxied: the addon routes it to the Django server, so everything lives on one port.
- The rules, the editor, history, metrics, rule content and the pause switch stay in Django.

A proxied request goes: mitmdump, the addon, `/api/proxy/decide`, the rule engine, back to the addon, which answers, kills the connection or lets it through. A direct request goes: mitmdump, the addon (rerouted), the middleware (CORS preflight), then `urls.py`: health / ui / ca.pem / admin, then `apis/fallback.py`: the pause switch (503), the rule engine, 404. A `disconnect` rule on a direct path comes back as an empty 204 with an `X-Mock-Hangup` header, which the addon turns into a killed connection.

## how to read the code

The layout follows what the big Django references agree on ([cookiecutter-django](https://github.com/cookiecutter/cookiecutter-django): a `config/` project package with split settings, `requirements/` split by environment, tests apart; [HackSoft Django-Styleguide](https://github.com/HackSoftware/Django-Styleguide): business logic in `services`, the HTTP layer thin in `apis`, tests mirroring the layers), cut down to a tool with no database.

```
manage.py                    Django's command line, `runmock` is the entry point
pyproject.toml               black, pylint, bandit and pytest settings in one place
requirements/                base.txt (django, mitmproxy), local.txt (+ pytest, requests, black, bandit, pylint)
scripts/                     first_setup.sh, run_tests.sh, checks.sh
data/                        rules.json (the tracked seed); hits, history, rule_content, ca/ appear here at runtime, git-ignored
config/                      the project package, no logic
  settings/base.py           what every run shares (no db, no sessions, one middleware)
  settings/local.py          the machine: allowed hosts, secret key, the data dir (a mock proxy is never deployed, so no production.py)
  urls.py  wsgi.py
mocks/                       the one app
  conf.py                    data paths, version, limits
  state.py                   the singletons: engine, admin facade, mitmdump's port
  urls.py                    the whole route table, first match wins, unclaimed paths are the rule engine's
  middleware.py              CORS preflights, before URL routing
  apis/                      thin HTTP layer: read the request, call a service, shape the response
    routing.py               the method gate (405, or fall through to the rule engine)
    helpers.py               reply(), query, JSON body, raw request line and headers
    system.py                health, ui, ca.pem, /api/send, version
    rules.py                 rules, rule_item (export/import/test), toggle, history
    content.py               rule-content list, put, delete, public get
    runtime.py               pause switch, metrics
    proxy.py                 /api/proxy/decide and /seen, the two calls the addon makes
    fallback.py              a direct request nothing claimed: pause 503, rules, 404
  services/                  the domain, no HTTP in here
    engine.py                pick the winning rule, run it
    matching.py              does a rule match a request
    actions.py               overrides, synthetic responses, proxyTo replay, {host} macro
    storage.py               RuleStore (live reload by mtime/size), Metrics
    content.py               stored rule content, bodyHTML references
    messages.py              the request dict and its header helpers
    decisions.py             decide(): respond / disconnect / let through, as data
    admin.py                 validation, save/delete/toggle/import, history, tester
  proxy/                     the mitmdump side
    mitm.py                  finds the binary, builds its command line
    addon.py                 the mitmproxy addon (runs inside mitmdump: stdlib + mitmproxy only)
    serving.py               the rule manager's loopback wsgi server
  management/commands/runmock.py   starts the rule manager, then mitmdump, ends both together
  web/ui.html                plain HTML, native dialog + a few lines of CSS, served as is
tests/                       conftest.py (self-starting server, make_rule, local upstreams), mirrors the layers
  api/                       admin api, health/ui/cors
  services/                  rule actions, match matrix (csv-driven, data_driven/)
  proxy/                     proxy and https behaviour, the binary lookup
```

There is no `selectors` layer (HackSoft's read side): reads here are two-line lookups in the services, and a separate module would only be an empty hop.

### the rule engine

The lowest `priority` number wins; inactive and soft-deleted rules never fire. A rule is `match` plus any of:

- `disconnect` closes the socket without a reply
- `delayMs` sleeps once, in the request phase, capped at 30000
- `requestOverride` rewrites `url`, `method`, headers (`headersReplace`, `headersRemove`) and body (`bodyReplace` by dot-path, `bodySet`, `rawBodyReplace`) before the request is forwarded
- `responseOverride` answers synthetically: `status`, `headersReplace`, `bodySet`, `bodyHTML` (a `{host}/rule-content/<name>` reference serves stored content)
- `proxyTo` replays the (possibly rewritten) request against an http(s) origin, 502 otherwise

`{host}` resolves to `127.0.0.1`. `rules.json` is re-read whenever its mtime or size changes; writes are atomic (tmp file + rename), with no restart and no watcher thread.

The seed rules in `data/rules.json`: `yahoo-mail-down` (503), `yahoo-news-slow` (GET, 300 ms delay, 200), `yahoo-finance-hangup` (disconnect), `yahoo-search-limited` (429), and `yahoo-weather-forward` (inactive, `proxyTo` a local server on :40000).

### endpoints

```
GET  /health, /api/version
GET  /ui                                      the editor
GET  /api/rules[?includeDeleted=1]            POST /api/rules   (name from "rule-name")
GET|PUT|DELETE /api/rules/<name>              delete is soft, saving brings it back
POST /api/rules/<name>/toggle
GET  /api/rules/export       POST /api/rules/import   (partial-failure report)
POST /api/rules/test                          dry run, shows winner + all candidates, no side effects
GET  /api/history?name=<n>   POST /api/history/<id>/restore   (10 per rule, restore snapshots first)
GET|POST /api/mock-state                      {paused: bool}, the global kill-switch
GET  /api/metrics            POST /api/metrics/reset
GET|PUT|DELETE /api/rule-content[/<name>]     GET /rule-content/<name> (content-type by extension)
```

Saves are validated: errors are a 400 with an `errors` list, soft problems come back as `warnings`, and `?strict=1` turns warnings into errors.

### left out on purpose

The Node stack, Google auth, Mongo/S3 capture, ngrok and bundled Linux binaries (the mitmproxy reference ships ELF `mitmdump` files, which do not run on a Mac; this project installs mitmproxy from pip instead). No ORM either: rules are a JSON document that the editor and the file system both own (`rules.json`, re-read on change), so Django's database, auth and session apps stay out of `INSTALLED_APPS`. `proxyTo` is a plain urllib replay.

A mocked response keeps one value per header name (a rule's `headersReplace` is a plain object), hop-by-hop headers from a rule (`keep-alive`, `te`, `upgrade` ...) are not copied onto the reply, and the Django side drops headers with an underscore in the name (its spoofing guard).

## if it breaks

| symptom | cause | fix |
|---|---|---|
| `mitmdump not found` from `runmock` | `.venv` not built, or no binary on PATH | run `scripts/first_setup.sh`, or set `MITMDUMP_BIN` |
| `run_tests.sh`: `lacks django, pytest, pytest-html or requests` | no `.venv` | run `scripts/first_setup.sh` |
| `first_setup.sh` cannot find a Python | no `python3.11` on PATH | install Python 3.11 and make `python3.11` resolvable |
| `runmock` exits at once, port in use | something already listens on 38800 | `--port 9000`, or stop the other process |
| https request fails with a certificate error | the client neither trusts the mock's CA nor ignores errors | `curl -k`, or fetch `/ca.pem` and trust it |
| an https request through the proxy is not mocked | started with `--no-mitm` | restart without it |
| 502 page from mitmproxy | no rule matched and the real origin is unreachable (or its certificate is rejected) | check the network; `--insecure` for self-signed dev origins |
| `git status` shows `data/rules.json` modified | saving a rule through the API/UI rewrites the seed | `git checkout data/rules.json`, or run with `MOCK_DATA_DIR` |
| a rule does not fire | lower-priority number wins, or the rule is inactive/soft-deleted, or the match text is not in `host/path` | use `POST /api/rules/test` to see the winner and all candidates |

## next

- a fake API to point your client at: https://github.com/ClasherGeek77/reqresin_clone
- send requests by hand: https://github.com/ClasherGeek77/postman_collection or https://github.com/ClasherGeek77/bruno_collection
- tests that call a service you can now make fail on purpose: https://github.com/ClasherGeek77/pytest_api_boilerplate
