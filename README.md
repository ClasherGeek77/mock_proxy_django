# mock proxy django

the django twin of `../mock_proxy_python`, same behaviour one for one: a rule-driven mock proxy. point a client at it as its http proxy and the rules mock the answers they match while everything else goes through to the real origin. it is also the mock server for direct calls, its admin api and its editor ui at once. django 4.2 (the last that runs on python 3.8), no database, no sessions, no templates. built 2026-11-18. the rules engine is a port of the mitmproxy `rules.py` addon.

the split: django owns routing, requests, responses and the wsgi plumbing; the two things django cannot do, taking a proxy request line and a `CONNECT`, live in one small server class (`mocks/serving.py`) that hands everything else to django.

## how to run it

```bash
./first_setup.sh                   # once, builds .venv (django, pytest, requests, bandit, black, pylint)
.venv/bin/python manage.py runmock                 # http://127.0.0.1:38800
.venv/bin/python manage.py runmock --port 9000 [--no-mitm] [--insecure]
./run_tests.sh                     # 97 tests, the suite starts its own server on a free port
./run_e2e.sh                       # live: real server process + /ui driven in headless chrome (46 checks)
./checks.sh                        # bandit, black, pylint (10/10)
```

`MOCK_URL=http://127.0.0.1:38800 ./run_tests.sh` tests an already running server instead (the live-reload test skips, it needs the server's data dir). `MOCK_DATA_DIR` moves all mutable state (rules, history, hits, rule-content, the CA) off the checked-in files; the tests and the e2e run use it.

under any other wsgi server (`mockproxy.wsgi:application`) the admin api, the ui and direct mocking work; proxy mode and https interception need `runmock`, which owns the socket, and a `disconnect` rule can only answer an empty 204 there.

## using it as a proxy

```bash
curl -x http://127.0.0.1:38800 http://www.yahoo.com/mail            # mocked by a seed rule, works offline
curl -k -x http://127.0.0.1:38800 https://www.yahoo.com/mail        # https too, -k ignores the certificate
curl --cacert ca.pem -x http://127.0.0.1:38800 https://www.yahoo.com/mail   # or trust the mock's CA
http_proxy=http://127.0.0.1:38800 ./your-client                       # any client that honours the env var
```

- a request with a full url in its request line is proxy mode. rules match on the url as `host/path` (`urlContains` sees `www.yahoo.com/mail`, with or without a leading `http://` or `https://`), so a rule can target one host. no rule matches: the request is replayed to the real origin untouched (no redirect following), unreachable origin is a 502.
- `disconnect`, `delayMs`, `requestOverride`, `responseOverride` and `proxyTo` all work the same as for direct calls.
- pause stops mocking but the proxy keeps relaying, so a client that is configured to use it keeps working.
- a request that names the mock's own address is a direct call, so `/api`, `/ui` and `/health` are never reachable through a proxied foreign host.

### https

a `CONNECT` is opened up (man in the middle). the first time, a local CA is made with the `openssl` binary (`ca/ca.pem` + `ca/ca.key` in the data dir, git-ignored) and every host the client asks for gets a leaf certificate signed by it, made on demand and cached. the rules then see the https request inside, so `https://www.yahoo.com/mail` is mocked like the http one.

- the client has to either trust the CA (`GET /ca.pem`, also linked in the ui) or ignore certificate errors (`curl -k`, `verify=False`, a browser's "proceed"). a client that does neither is refused at the handshake, nothing is mocked and nothing leaks.
- no rule matches: the request is replayed to the real origin over https and the origin's certificate is verified. `--insecure` (or `MOCK_INSECURE=1`) skips that check for self-signed dev origins.
- a tunnel whose first bytes are not a TLS hello (ssh over CONNECT, say) stays a blind relay. `--no-mitm` relays all of it blindly again, a dead origin is then a 502 at the CONNECT.
- certificate-pinning apps will refuse the mock's certificate, that is the pin doing its job.
- the CA key is a signing key for any site: keep `ca/` private, delete the folder to make a new CA, and remove the CA from the trust store when you are done.

## shape

```
manage.py                 django's command line, `runmock` is the entry point
mockproxy/                settings (no db, one middleware), urls (the whole route table, first match wins, unclaimed paths are the rule engine's), wsgi
mocks/serving.py          the socket layer: proxy request lines, CONNECT, tls interception, hangup
mocks/middleware.py       proxy-mode requests and CORS preflights, before url routing
mocks/views.py            health, ui, ca.pem, /api/send, every /api route (thin, http only)
mocks/admin.py            validation, save/delete/toggle/import, history, tester, rule-content
mocks/mocking.py          engine decision -> django response, proxied relay, the 404 fallback
mocks/engine.py           RuleStore (live reload by mtime/size), Metrics, Engine, forward()
mocks/tlsca.py            the local CA and per-host leaf certificates (openssl binary)
mocks/ui.html             plain html, native dialog + a few lines of css, served as is
rules.json                5 seed rules on www.yahoo.com (mail 503, news slow, finance hang up, search 429, an inactive forward)
conftest.py               self-starting server fixture, make_rule, local upstream for proxyTo
tests/                    97 pytest tests (proxy and https in test_proxy.py), a csv-driven match matrix under data_driven/
e2e/ui_live.py            browser end-to-end of the editor, effects verified by independent http calls
```

a request goes: the middleware (proxy mode, preflight), then urls.py: health / ui / ca.pem / admin, then the catch-all view: the pause switch (503), the rule engine, 404.

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

the node stack, google auth, mongo/s3 capture, ngrok, mitmproxy itself and its 120 MB binaries. no orm either: rules are a json document the editor and the file system both own (`rules.json`, re-read on change), so django's database, auth and session apps stay out of `INSTALLED_APPS`. `proxyTo` is a plain urllib replay. the only outside tool is the `openssl` binary, used just to make certificates.

differences from the stdlib twin, all forced by wsgi: hop-by-hop headers from an origin (`keep-alive`, `te`, `upgrade` ...) are not copied onto the reply, a `HEAD` reply carries no `Content-Length`, a `Server:` header names wsgiref, and headers with an underscore in the name are dropped (django's spoofing guard).

## portfolio

sibling: `../mock_proxy_python`, the same suite and the same ui against the stdlib build.
