# mock proxy django

a rule-driven mock proxy. point a client at it as its http proxy and the rules mock the answers they match while everything else goes through to the real origin. it is also the mock server for direct calls, its admin api and its editor ui at once. the wire is the real **mitmproxy** (`mitmdump`); django 4.2 (the last that runs on python 3.8) is the rule manager behind it: no database, no sessions, no templates. built 2026-11-18. the rules engine is a port of the mitmproxy `rules.py` addon.

## why mitmdump in front

a proxy that mocks https is mostly wire work: `CONNECT`, a CA, a certificate per host, tls on both sides, http/1 and http/2, keep-alive, streaming, the real upstream call. that is what mitmproxy is for, so none of it is rewritten here.

```
client --> mitmdump :38800 --(addon asks: what do I do with this?)--> django rule manager (loopback, own port)
              |                                                         rules.json, admin api, ui, metrics
              +--> real origin (when the rules leave the request alone)
```

- `mocks/addon.py` is the mitmproxy addon, one decision per request: **respond** (a mocked response, the origin is never called), **disconnect** (kill the connection, no reply) or **none** (let it through, with the rule's request overrides applied). it speaks to django over a tiny json api (`/api/proxy/decide`, `/api/proxy/seen`).
- a request for the proxy's own port (`/ui`, `/api`, `/health`, a directly mocked path) is not proxied: the addon routes it to the django server, so everything is on one port like before.
- the rules, the editor, history, metrics, rule-content and the pause switch stay in django.

## how to run it

```bash
./first_setup.sh                   # once: .venv (django, pytest, requests, bandit, black, pylint) and .venv-mitm (mitmproxy)
.venv/bin/python manage.py runmock                 # http://127.0.0.1:38800
.venv/bin/python manage.py runmock --port 9000 [--no-mitm] [--insecure]
./run_tests.sh                     # 104 tests, the suite starts its own server on a free port
./checks.sh                        # bandit, black, pylint (10/10)
```

`runmock` finds the binary in this order: `MITMDUMP_BIN`, `.venv-mitm/bin/mitmdump`, `mitmdump` on `PATH` (so `brew install mitmproxy` works too). mitmproxy needs python 3.10+, which is why it has its own venv (`MITM_PYTHON=/path/to/python3.11 ./first_setup.sh` picks the interpreter). the version is pinned in `requirements-mitm.pip`; 11.0.2 is the one checked on macOS 10.15. a plain kill of `runmock` takes mitmdump down with it.

`MOCK_URL=http://127.0.0.1:38800 ./run_tests.sh` tests an already running server instead (the live-reload test skips, it needs the server's data dir). `MOCK_DATA_DIR` moves all mutable state (rules, history, hits, rule-content, the CA) off the checked-in files; the tests use it.

mitmdump prints one line per flow (method, url, status), so a demo shows the traffic as it happens.

## using it as a proxy

```bash
curl -x http://127.0.0.1:38800 http://www.yahoo.com/mail            # mocked by a seed rule, works offline
curl -k -x http://127.0.0.1:38800 https://www.yahoo.com/mail        # https too, -k ignores the certificate
curl --cacert ca.pem -x http://127.0.0.1:38800 https://www.yahoo.com/mail   # or trust the mock's CA
http_proxy=http://127.0.0.1:38800 ./your-client                       # any client that honours the env var
```

- a request with a full url in its request line is proxy mode. rules match on the url as `host/path` (`urlContains` sees `www.yahoo.com/mail`, with or without a leading `http://` or `https://`), so a rule can target one host. no rule matches: mitmdump calls the real origin, with the rule's `requestOverride` applied if there was one. an unreachable origin is mitmproxy's own 502 page.
- `disconnect`, `delayMs`, `requestOverride`, `responseOverride` and `proxyTo` all work the same as for direct calls. a delay stalls that one flow only.
- pause stops mocking but the proxy keeps relaying, so a client that is configured to use it keeps working.
- a request that names the mock's own address is a direct call, so `/api`, `/ui` and `/health` are never reachable through a proxied foreign host.

### https

mitmdump opens a `CONNECT` up (man in the middle). its CA is made on the first start (`ca/mitmproxy-ca-cert.pem` and the key in the data dir, git-ignored) and every host gets a certificate signed by it. the rules then see the https request inside, so `https://www.yahoo.com/mail` is mocked like the http one.

- the client has to either trust the CA (`GET /ca.pem`, also linked in the ui) or ignore certificate errors (`curl -k`, `verify=False`, a browser's "proceed"). a client that does neither is refused at the handshake, nothing is mocked and nothing leaks.
- no rule matches: the request goes to the real origin over https and the origin's certificate is verified. `--insecure` (or `MOCK_INSECURE=1`) skips that check for self-signed dev origins.
- `--no-mitm` tunnels https untouched (`--ignore-hosts .*`): the rules only see plain http, a dead origin is a 502 at the `CONNECT`.
- certificate-pinning apps will refuse the mock's certificate, that is the pin doing its job.
- the CA key is a signing key for any site: keep `ca/` private, delete the folder to make a new CA, and remove the CA from the trust store when you are done.

## shape

```
manage.py                 django's command line, `runmock` is the entry point
mockproxy/                settings (no db, one middleware), urls (the whole route table, first match wins, unclaimed paths are the rule engine's), wsgi
mocks/management/.../runmock.py   starts the rule manager, then mitmdump with the addon, and ends both together
mocks/mitm.py             finds the mitmdump binary, builds its command line
mocks/addon.py            the mitmproxy addon (runs inside mitmdump: stdlib + mitmproxy only)
mocks/serving.py          the rule manager's wsgi server, loopback only
mocks/middleware.py       CORS preflights, before url routing
mocks/views.py            health, ui, ca.pem, /api/send, /api/proxy/*, every /api route (thin, http only)
mocks/admin.py            validation, save/delete/toggle/import, history, tester, rule-content
mocks/mocking.py          decide(): engine verdict for a request, the 404 fallback for direct ones
mocks/engine.py           RuleStore (live reload by mtime/size), Metrics, Engine, forward()
mocks/ui.html             plain html, native dialog + a few lines of css, served as is
rules.json                5 seed rules on www.yahoo.com (mail 503, news slow, finance hang up, search 429, an inactive forward)
conftest.py               self-starting server fixture, make_rule, local upstream for proxyTo
tests/                    104 pytest tests (proxy and https in test_proxy.py, the binary lookup in test_mitm.py), a csv-driven match matrix under data_driven/
```

a proxied request goes: mitmdump, the addon, `/api/proxy/decide`, the rule engine, back to the addon, which answers, kills or lets it through. a direct request goes: mitmdump, the addon (rerouted), the middleware (preflight), then urls.py: health / ui / ca.pem / admin, then the catch-all view: the pause switch (503), the rule engine, 404. a `disconnect` rule on a direct path comes back as an empty 204 with an `X-Mock-Hangup` header, which the addon turns into a killed connection.

## the rule engine

lowest `priority` number wins, inactive and soft-deleted rules never fire. a rule is `match` plus any of:

- `disconnect` closes the socket without a reply
- `delayMs` sleeps once, in the request phase, capped at 30000
- `requestOverride` rewrites `url`, `method`, headers (`headersReplace`, `headersRemove`) and body (`bodyReplace` by dot-path, `bodySet`, `rawBodyReplace`) before it is forwarded
- `responseOverride` answers synthetically: `status`, `headersReplace`, `bodySet`, `bodyHTML` (a `{host}/rule-content/<name>` reference serves stored content)
- `proxyTo` replays the (possibly rewritten) request against an http(s) origin, 502 otherwise

`{host}` resolves to `127.0.0.1`. `rules.json` is re-read whenever its mtime or size changes, writes are atomic (tmp + rename), no restart and no watcher thread.

## endpoints

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

saves validate: errors are a 400 with an `errors` list, soft problems come back as `warnings`, and `?strict=1` turns warnings into errors.

## left out on purpose

the node stack, google auth, mongo/s3 capture, ngrok and the 120 MB bundled linux binaries (the reference ships elf `mitmdump`, which does not run on a mac; this one installs mitmproxy from pip instead). no orm either: rules are a json document the editor and the file system both own (`rules.json`, re-read on change), so django's database, auth and session apps stay out of `INSTALLED_APPS`. `proxyTo` is a plain urllib replay.

a mocked response keeps one value per header name (a rule's `headersReplace` is a plain object), hop-by-hop headers from a rule (`keep-alive`, `te`, `upgrade` ...) are not copied onto the reply, and the django side drops headers with an underscore in the name (its spoofing guard).
