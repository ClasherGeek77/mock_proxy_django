#!/bin/bash
# security (bandit), format (black) and lint (pylint, must be 10/10) over everything
# all three live in this repo's .venv (requirements/local.txt), django included so pylint
# can resolve it
set -e
cd "$(dirname "$0")/.."

PY=${PY:-.venv/bin/python}
if [ ! -x "$PY" ]; then
    echo "missing interpreter $PY, run scripts/first_setup.sh"
    exit 1
fi

CODE="manage.py config mocks tests"

echo "Security check (bandit)"
"$PY" -m bandit --recursive $CODE -c pyproject.toml --quiet

echo "Format check (black)"
"$PY" -m black --check --quiet $CODE

echo "Lint check (pylint)"
"$PY" -m pylint --rcfile=pyproject.toml $CODE
