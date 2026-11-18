#!/bin/bash
# one-time setup: builds .venv from requirements/local.txt with the interpreter named in
# .python-version (3.11.14, same as the other boilerplates): django, pytest, requests,
# mitmproxy (the mitmdump binary the proxy runs on) and the bandit/black/pylint that
# checks.sh runs. skip mitmproxy by pointing MITMDUMP_BIN at another mitmdump
set -e
cd "$(dirname "$0")/.."

if .venv/bin/python -c "import django, pytest, pytest_html, requests" > /dev/null 2>&1 && [ -x .venv/bin/mitmdump ]; then
    echo "ready: .venv has django, pytest, pytest-html, requests and mitmdump, nothing to install"
    exit 0
fi

PYTHON_MINOR=$(cut -d. -f1,2 .python-version)
PYTHON=python$PYTHON_MINOR
command -v "$PYTHON" > /dev/null || PYTHON="$HOME/camoufox-env/bin/python$PYTHON_MINOR"
echo "creating .venv with $($PYTHON --version) (needs network for pip)"
$PYTHON -m venv .venv
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/python -m pip install -q -r requirements/local.txt
echo "done, run scripts/run_tests.sh"
