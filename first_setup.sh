#!/bin/bash
# one-time setup, two venvs:
#   .venv       django, pytest, requests and the bandit/black/pylint checks.sh runs
#               (the interpreter in .python-version, django 4.2 is the last one for 3.8)
#   .venv-mitm  the mitmdump binary the proxy runs on. mitmproxy needs python >= 3.10, so
#               it lives apart from .venv. MITM_PYTHON picks the interpreter; skip this
#               one entirely with `brew install mitmproxy` or MITMDUMP_BIN=/path/to/mitmdump
set -e
cd "$(dirname "$0")"

if .venv/bin/python -c "import django, pytest, pytest_html, requests" > /dev/null 2>&1; then
    echo "ready: .venv has django, pytest, pytest-html and requests"
else
    PYTHON_MINOR=$(cut -d. -f1,2 .python-version)
    PYTHON=python$PYTHON_MINOR
    command -v "$PYTHON" > /dev/null || PYTHON=python3
    echo "creating .venv with $($PYTHON --version) (needs network for pip)"
    $PYTHON -m venv .venv
    .venv/bin/python -m pip install -q --upgrade pip
    .venv/bin/python -m pip install -q -r requirements.pip
fi

if [ -x .venv-mitm/bin/mitmdump ] || [ -n "$MITMDUMP_BIN" ] || command -v mitmdump > /dev/null; then
    echo "ready: mitmdump found"
else
    MITM_PYTHON=${MITM_PYTHON:-}
    if [ -z "$MITM_PYTHON" ]; then
        for cand in python3.13 python3.12 python3.11 python3.10 "$HOME/camoufox-env/bin/python3.11"; do
            if command -v "$cand" > /dev/null; then MITM_PYTHON=$(command -v "$cand"); break; fi
        done
    fi
    if [ -z "$MITM_PYTHON" ]; then
        echo "no python >= 3.10 found for mitmproxy: set MITM_PYTHON, or brew install mitmproxy"
        exit 1
    fi
    echo "creating .venv-mitm with $($MITM_PYTHON --version) (needs network for pip)"
    "$MITM_PYTHON" -m venv .venv-mitm
    .venv-mitm/bin/python -m pip install -q --upgrade pip
    .venv-mitm/bin/python -m pip install -q -r requirements-mitm.pip
fi
echo "done, run ./run_tests.sh"
