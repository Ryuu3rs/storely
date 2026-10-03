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

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

KEY_FILE = Path(os.environ.get("USERPROFILE", str(Path.home()))) / ".storely-release" / "ed25519_private.pem"
ENV_VAR = "STORELY_SIGNING_KEY"
UPDATER = Path(__file__).resolve().parent.parent / "storemgr" / "updater.py"


def public_b64(key: Ed25519PrivateKey) -> str:
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode()


def _from_pem(pem: bytes, where: str) -> Ed25519PrivateKey:
    try:
        key = serialization.load_pem_private_key(pem, password=None)
    except (ValueError, TypeError) as e:
        sys.exit(f"{where} is not an unencrypted PEM private key: {e}")
    if not isinstance(key, Ed25519PrivateKey):
        sys.exit(f"{where} is not an Ed25519 key")
    return key


def load_private_key() -> Ed25519PrivateKey:
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
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
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
