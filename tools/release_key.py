"""Makes the Ed25519 key that signs Storely releases (see sign_release.py). The private key stays outside the repo,
in %USERPROFILE%\\.storely-release\\ed25519_private.pem; paste the printed public key into storemgr/updater.py PUBLIC_KEY.
Run: .venv\\Scripts\\python.exe tools\\release_key.py              new key (refuses to replace an existing one)
     .venv\\Scripts\\python.exe tools\\release_key.py --show       public key of the existing key file
     python tools/release_key.py --from-env                       CI: public key of the PEM in STORELY_SIGNING_KEY,
                                                                  fails if it isn't the one built into the app"""

from __future__ import annotations

import argparse
import base64
import os
import re
import sys
from pathlib import Path

from nacl.signing import SigningKey

KEY_FILE = Path(os.environ.get("USERPROFILE", str(Path.home()))) / ".storely-release" / "ed25519_private.pem"
ENV_VAR = "STORELY_SIGNING_KEY"
UPDATER = Path(__file__).resolve().parent.parent / "storemgr" / "updater.py"
# PKCS#8 wrapping of an Ed25519 private key is a fixed 16-byte header followed by the 32-byte seed
PKCS8_PREFIX = bytes.fromhex("302e020100300506032b657004220420")


def public_b64(key: SigningKey) -> str:
    return base64.b64encode(bytes(key.verify_key)).decode()


def to_pem(key: SigningKey) -> bytes:
    body = base64.b64encode(PKCS8_PREFIX + bytes(key)).decode()
    return f"-----BEGIN PRIVATE KEY-----\n{body}\n-----END PRIVATE KEY-----\n".encode()


def _from_pem(pem: bytes, where: str) -> SigningKey:
    m = re.search(rb"-----BEGIN PRIVATE KEY-----(.+?)-----END PRIVATE KEY-----", pem, re.S)
    try:
        der = base64.b64decode(b"".join(m.group(1).split()), validate=True) if m else b""
    except ValueError:
        der = b""
    if len(der) != 48 or not der.startswith(PKCS8_PREFIX):
        sys.exit(f"{where} is not an unencrypted Ed25519 PEM private key")
    return SigningKey(der[16:])


def load_private_key() -> SigningKey:
    """The signing key from STORELY_SIGNING_KEY if set (CI), else from KEY_FILE."""
    pem = os.environ.get(ENV_VAR, "").strip()
    if pem:
        return _from_pem(pem.encode() + b"\n", ENV_VAR)
    if not KEY_FILE.is_file():
        sys.exit(f"no signing key: set {ENV_VAR} or run tools\\release_key.py to create {KEY_FILE}")
    return _from_pem(KEY_FILE.read_bytes(), str(KEY_FILE))


def app_public_key() -> str:
    """PUBLIC_KEY as written in storemgr/updater.py (read from source so the app package isn't imported)."""
    m = re.search(r'^PUBLIC_KEY\s*=\s*"([^"]*)"', UPDATER.read_text(encoding="utf-8"), re.MULTILINE)
    return m.group(1) if m else ""


def create() -> None:
    key = SigningKey.generate()
    pem = to_pem(key)
    KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(KEY_FILE, "xb") as f:
            f.write(pem)
    except FileExistsError:
        sys.exit(f"{KEY_FILE} already exists - not replacing it (every installed copy trusts that key). "
                 "Use --show to print its public key.")
    print(f"private key written to {KEY_FILE} - back it up somewhere safe and never commit it")
    print(f"public key (paste into storemgr/updater.py PUBLIC_KEY):\n{public_b64(key)}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Create or inspect the Storely release-signing key.")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--show", action="store_true", help="print the public key of the existing key file")
    g.add_argument("--from-env", action="store_true", help=f"use the PEM in {ENV_VAR} and check it matches the app")
    a = ap.parse_args()
    if a.from_env:
        if not os.environ.get(ENV_VAR, "").strip():
            sys.exit(f"{ENV_VAR} is not set")
        pub = public_b64(load_private_key())
        print(pub)
        if pub != app_public_key():
            sys.exit(f"the key in {ENV_VAR} does not match PUBLIC_KEY in storemgr/updater.py - "
                     "installed copies would reject updates signed with it")
    elif a.show:
        if not KEY_FILE.is_file():
            sys.exit(f"{KEY_FILE} doesn't exist")
        print(public_b64(_from_pem(KEY_FILE.read_bytes(), str(KEY_FILE))))
    else:
        create()


if __name__ == "__main__":
    main()
