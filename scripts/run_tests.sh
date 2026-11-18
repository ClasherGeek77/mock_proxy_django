#!/bin/bash
# run the pytest suite without remembering any syntax
#   ./scripts/run_tests.sh                              everything
#   ./scripts/run_tests.sh tests/test_admin.py          one file, any pytest args are passed through
#   MOCK_URL=http://127.0.0.1:38800 ./scripts/run_tests.sh   test an already running server
# the suite starts its own server on a free port, nothing has to be running
# the interpreter is this repo's .venv (django must be importable, see first_setup.sh)
cd "$(dirname "$0")/.."

PYTHON=${PYTEST_PYTHON:-.venv/bin/python}
if ! "$PYTHON" -c "import django, pytest, pytest_html, requests" > /dev/null 2>&1; then
    echo "$PYTHON lacks django, pytest, pytest-html or requests, run scripts/first_setup.sh"
    exit 1
fi

mkdir -p reports
echo "using $PYTHON"
exec "$PYTHON" -m pytest "$@"
