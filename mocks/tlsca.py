"""Certificate authority for https interception: stdlib + the openssl binary.

A CONNECT to a host can be opened up (man in the middle) so the rules see the https
request inside it. The first start makes a local CA (ca.pem + ca.key) in
<data dir>/ca/, each host then gets a leaf certificate signed by it, made on demand
and cached. A client either trusts ca.pem (GET /ca.pem) or ignores certificate
errors (curl -k).
"""

import os
import re
import secrets
import shutil
import ssl
import subprocess  # nosec B404 - runs the local openssl binary with a fixed argv
import tempfile
import threading

HOST_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$|^[0-9A-Fa-f:]{2,45}$")
CA_CONF = """[req]
distinguished_name = dn
x509_extensions = v3
prompt = no
[dn]
CN = Mock Proxy CA
[v3]
basicConstraints = critical,CA:true
keyUsage = critical,keyCertSign,cRLSign
subjectKeyIdentifier = hash
"""


class CAError(Exception):
    pass


class CA:
    def __init__(self, folder):
        self.dir = folder
        self.cert = os.path.join(folder, "ca.pem")
        self.key = os.path.join(folder, "ca.key")
        self.leaf_key = os.path.join(folder, "leaf.key")
        self.openssl = shutil.which("openssl")
        self.lock = threading.Lock()
        self.contexts = {}

    def run(self, *args):
        if not self.openssl:
            raise CAError("openssl binary not found")
        try:
            # fixed argv, no shell; the only variable parts are file names we made
            # and a host name that passed HOST_OK
            subprocess.run(  # nosec B603
                [self.openssl, *args], check=True, capture_output=True, timeout=30
            )
        except (subprocess.SubprocessError, OSError) as exc:
            raise CAError(f"openssl failed: {exc}") from exc

    def ensure(self):
        """Make the CA and the shared leaf key once (idempotent)."""
        with self.lock:
            if os.path.exists(self.cert) and os.path.exists(self.leaf_key):
                return
            os.makedirs(self.dir, mode=0o700, exist_ok=True)
            conf = os.path.join(self.dir, "ca.cnf")
            with open(conf, "w", encoding="utf-8") as fh:
                fh.write(CA_CONF)
            self.run("genrsa", "-out", self.key, "2048")
            os.chmod(self.key, 0o600)
            self.run(
                *("req", "-x509", "-new", "-key", self.key, "-out", self.cert),
                *("-days", "3650", "-config", conf),
            )
            self.run("genrsa", "-out", self.leaf_key, "2048")
            os.chmod(self.leaf_key, 0o600)

    def context(self, host):
        """A server-side ssl context holding a certificate for host."""
        host = host.lower().strip("[]")
        if not HOST_OK.match(host):
            raise CAError("not a usable host name")
        self.ensure()
        with self.lock:
            if host in self.contexts:
                return self.contexts[host]
            pem = self.leaf(host)
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(pem, self.leaf_key)
            self.contexts[host] = ctx
            return ctx

    def leaf(self, host):
        is_ip = ":" in host or re.fullmatch(r"[0-9.]+", host) is not None
        san = ("IP:" if is_ip else "DNS:") + host
        ext = f"subjectAltName = {san}\nextendedKeyUsage = serverAuth\n"
        ext += (
            "basicConstraints = CA:FALSE\nkeyUsage = digitalSignature,keyEncipherment\n"
        )
        out = os.path.join(
            self.dir, "leaf-" + re.sub(r"[^0-9a-z.-]", "_", host) + ".pem"
        )
        with tempfile.TemporaryDirectory(dir=self.dir) as tmp:
            csr, extfile = os.path.join(tmp, "x.csr"), os.path.join(tmp, "x.ext")
            with open(extfile, "w", encoding="utf-8") as fh:
                fh.write(ext)
            self.run(
                *("req", "-new", "-key", self.leaf_key, "-out", csr),
                *("-subj", "/CN=" + host[:60]),
            )
            self.run(
                *("x509", "-req", "-in", csr, "-CA", self.cert, "-CAkey", self.key),
                *("-set_serial", str(secrets.randbits(63)), "-out", out),
                *("-days", "397", "-extfile", extfile),
            )
        return out
