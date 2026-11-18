#!/bin/bash
# live end-to-end: a real server process (state in a temp dir, free port) + the /ui in headless Chrome
#   ./run_e2e.sh
# needs selenium + Chrome + chromedriver, borrowed from ../pytest_boilerplate_web
# (override with E2E_PYTHON, CHROME_BIN is read by the script's default, CHROMEDRIVER_BIN)
cd "$(dirname "$0")"
WEB=../pytest_boilerplate_web
PYTHON=${E2E_PYTHON:-$WEB/.venv/bin/python}
export CHROMEDRIVER_BIN=${CHROMEDRIVER_BIN:-$WEB/tools/chromedriver}
"$PYTHON" -c "import selenium" 2> /dev/null || { echo "no selenium in $PYTHON, set E2E_PYTHON"; exit 1; }

TMP=$(mktemp -d /tmp/mock_e2e.XXXXXX)
cp rules.json "$TMP"
PORT=$(python3 -c "import socket;s=socket.socket();s.bind(('127.0.0.1',0));print(s.getsockname()[1])")
MOCK_DATA_DIR=$TMP .venv/bin/python manage.py runmock --port "$PORT" > "$TMP/server.log" 2>&1 &
SERVER=$!
trap 'kill $SERVER 2> /dev/null; rm -rf "$TMP"' EXIT
for _ in $(seq 50); do curl -s --noproxy '*' "http://127.0.0.1:$PORT/health" > /dev/null && break; sleep 0.1; done

MOCK_URL=http://127.0.0.1:$PORT E2E_TMP=$TMP "$PYTHON" e2e/ui_live.py
