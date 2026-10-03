"""Signs a release: writes SHA256SUMS (hash + two spaces + name for every Unjammed-Setup-*.exe in <dir>) and
SHA256SUMS.sig (base64 Ed25519 signature of SHA256SUMS). Upload both next to the installers.
Key: UNJAMMED_SIGNING_KEY (PEM, for CI) if set, else %USERPROFILE%\\.unjammed-release\\ed25519_private.pem.
Run: .venv\\Scripts\\python.exe tools\\sign_release.py dist"""

from __future__ import annotations

import base64
import hashlib
import re
import sys
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

sys.path.insert(0, str(Path(__file__).resolve().parent))
from release_key import app_public_key, load_private_key, public_b64

NAME_RE = re.compile(r"Unjammed-Setup-\d+\.\d+\.\d+\.0-(x64|arm64)\.exe")     # same as updater.INSTALLER_RE


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def publish(tag: str) -> None:
    """Sign a draft GitHub release that CI built: download its installers, sign, upload SUMS + .sig, publish."""
    import subprocess
    import tempfile
    if not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        sys.exit("usage: sign_release.py --publish vX.Y.Z")
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["gh", "release", "download", tag, "--pattern", "Unjammed-Setup-*.exe", "--dir", tmp], check=True)
        sign(Path(tmp))
        subprocess.run(["gh", "release", "upload", tag, str(Path(tmp) / "SHA256SUMS"), str(Path(tmp) / "SHA256SUMS.sig"),
                        "--clobber"], check=True)
    subprocess.run(["gh", "release", "edit", tag, "--draft=false", "--latest"], check=True)
    print(f"published {tag}")


def main() -> None:
    if len(sys.argv) == 3 and sys.argv[1] == "--publish":
        publish(sys.argv[2])
        return
    if len(sys.argv) != 2 or not Path(sys.argv[1]).is_dir():
        sys.exit("usage: sign_release.py <folder with the Unjammed-Setup-*.exe installers> | --publish vX.Y.Z")
    sign(Path(sys.argv[1]))


def sign(folder: Path) -> None:
    files = sorted(p for p in folder.glob("Unjammed-Setup-*.exe") if p.is_file())
    if not files:
        sys.exit(f"no Unjammed-Setup-*.exe in {folder}")
    bad = [p.name for p in files if not NAME_RE.fullmatch(p.name)]
    if bad:
        sys.exit(f"unexpected installer names (want Unjammed-Setup-X.Y.Z.0-x64|arm64.exe): {', '.join(bad)}")

    key = load_private_key()
    pub = public_b64(key)
    if pub != app_public_key():
        sys.exit("the signing key doesn't match PUBLIC_KEY in storemgr/updater.py - installed copies would reject it")
    sums = "".join(f"{sha256(p)}  {p.name}\n" for p in files).encode()
    sig = key.sign(sums)
    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(pub)).verify(sig, sums)
    except InvalidSignature:
        sys.exit("self-check of the new signature failed")
    (folder / "SHA256SUMS").write_bytes(sums)
    (folder / "SHA256SUMS.sig").write_bytes(base64.b64encode(sig) + b"\n")
    print(sums.decode(), end="")
    print(f"signed {len(files)} installer(s) -> {folder / 'SHA256SUMS'} + SHA256SUMS.sig")


if __name__ == "__main__":
    main()
