"""Find and start the mitmdump binary the proxy runs on."""

import os
import shutil
import subprocess  # nosec B404

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))  # the project folder, where .venv lives
ADDON = os.path.join(HERE, "addon.py")
HINT = "run scripts/first_setup.sh, or brew install mitmproxy, or set MITMDUMP_BIN"


def find_mitmdump():
    """MITMDUMP_BIN, then this project's .venv, then mitmdump on PATH."""
    local = os.path.join(ROOT, ".venv", "bin", "mitmdump")
    for path in (os.environ.get("MITMDUMP_BIN"), local, shutil.which("mitmdump")):
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


def command(binary, host, port, manager, confdir, intercept=True, insecure=False):
    cmd = [binary, "--listen-host", host, "--listen-port", str(port), "-s", ADDON]
    cmd += ["--set", f"mock_manager={manager}", "--set", f"confdir={confdir}"]
    if insecure:  # self-signed dev origins
        cmd += ["--set", "ssl_insecure=true"]
    if not intercept:  # tunnel https untouched, the rules only see plain http
        cmd += ["--ignore-hosts", ".*"]
    return cmd


# what a python started from another venv leaves behind (mitmdump has its own)
FOREIGN_PYTHON = ("__PYVENV_LAUNCHER__", "PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV")


def start(cmd):
    env = {k: v for k, v in os.environ.items() if k not in FOREIGN_PYTHON}
    # fixed argv: the binary we resolved, our own addon file and numbers we chose
    return subprocess.Popen(
        cmd, env=env
    )  # pylint: disable=consider-using-with  # nosec B603
