#!/bin/bash
# one-time setup: builds .venv from requirements.pip (django, pytest, requests and the
# bandit/black/pylint that checks.sh runs). django has to be importable by the
# interpreter the tests run under, because the suite starts `manage.py runmock` with it,
# so unlike the stdlib sibling there is no borrowing of another boilerplate's venv
set -e
cd "$(dirname "$0")"

if .venv/bin/python -c "import django, pytest, pytest_html, requests" > /dev/null 2>&1; then
    echo "ready: .venv already has django, pytest, pytest-html and requests, nothing to install"
    exit 0
fi

PYTHON_MINOR=$(cut -d. -f1,2 .python-version)
PYTHON=python$PYTHON_MINOR
command -v "$PYTHON" > /dev/null || PYTHON=python3
echo "creating .venv with $($PYTHON --version) (needs network for pip)"
$PYTHON -m venv .venv
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/python -m pip install -q -r requirements.pip
echo "done, run ./run_tests.sh"
