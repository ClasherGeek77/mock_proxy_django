#!/usr/bin/env python3
"""Django's command line: `python3 manage.py runmock` starts the mock proxy."""
import os
import sys


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mockproxy.settings")
    from django.core.management import (  # pylint: disable=import-outside-toplevel
        execute_from_command_line,
    )

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
